#!/usr/bin/env python3
"""
RDS PostgreSQL 备份脚本
单次执行，将数据库备份到 S3
定时任务由 ECS Scheduled Tasks 触发
"""

import os
import sys
import boto3
import subprocess
import logging
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置（从环境变量读取）
RDS_HOST = os.environ.get('RDS_HOST')
RDS_PORT = os.environ.get('RDS_PORT', '5432')
RDS_DB_NAME = os.environ.get('RDS_DB_NAME')
RDS_USERNAME = os.environ.get('RDS_USERNAME')
RDS_PASSWORD = os.environ.get('RDS_PASSWORD')
S3_BUCKET_RAW = os.environ.get('S3_BUCKET', '')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
CLOUDWATCH_NAMESPACE = os.environ.get('CLOUDWATCH_NAMESPACE', 'RDS/Backup')
# AWS 区域（优先使用 AWS_REGION，其次 AWS_DEFAULT_REGION，默认 us-east-1）
AWS_REGION = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'ap-northeast-1'

# 解析 S3_BUCKET：如果包含路径，分离出 bucket 名称和路径前缀
# 例如 "laravel-ops-data/db-backups" -> bucket="laravel-ops-data", prefix="db-backups/"
if S3_BUCKET_RAW:
    if '/' in S3_BUCKET_RAW:
        parts = S3_BUCKET_RAW.split('/', 1)
        S3_BUCKET = parts[0]
        S3_PREFIX = parts[1].rstrip('/') + '/' if parts[1] else ''
    else:
        S3_BUCKET = S3_BUCKET_RAW
        S3_PREFIX = ''
else:
    S3_BUCKET = ''
    S3_PREFIX = ''

# AWS 客户端（指定区域）
s3_client = boto3.client('s3', region_name=AWS_REGION)
sns_client = boto3.client('sns', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)

def send_cloudwatch_metric(metric_name, value, unit='Count', status='Success'):
    """发送 CloudWatch 指标"""
    try:
        cloudwatch.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': value,
                    'Unit': unit,
                    'Dimensions': [
                        {
                            'Name': 'Database',
                            'Value': RDS_DB_NAME
                        },
                        {
                            'Name': 'Status',
                            'Value': status
                        }
                    ]
                }
            ]
        )
    except NoCredentialsError:
        logger.warning("发送 CloudWatch 指标失败: 未找到 AWS 凭证（在 ECS 中应使用 IAM 角色，本地运行需要配置 AWS 凭证）")
    except Exception as e:
        logger.warning(f"发送 CloudWatch 指标失败: {e}")

def send_sns_notification(subject, message):
    """发送 SNS 通知（如果配置了 SNS_TOPIC_ARN）"""
    if not SNS_TOPIC_ARN:
        return
    
    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message
        )
        logger.info(f"SNS 通知已发送: {subject}")
    except NoCredentialsError:
        logger.warning(f"发送 SNS 通知失败: 未找到 AWS 凭证（在 ECS 中应使用 IAM 角色，本地运行需要配置 AWS 凭证）")
    except ClientError as e:
        logger.error(f"发送 SNS 通知失败: {e}")
    except Exception as e:
        logger.error(f"发送 SNS 通知失败: {e}")

def upload_to_s3(file_path, bucket, key):
    """上传文件到 S3"""
    try:
        s3_client.upload_file(file_path, bucket, key)
        logger.info(f"成功上传到 S3: s3://{bucket}/{key}")
        return True
    except NoCredentialsError:
        logger.error("上传到 S3 失败: 未找到 AWS 凭证（在 ECS 中应使用 IAM 角色，本地运行需要配置 AWS 凭证）")
        return False
    except ClientError as e:
        logger.error(f"上传到 S3 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"上传到 S3 失败: {e}")
        return False

def main():
    """主函数"""
    # 检查必需的环境变量
    required_vars = {
        'RDS_HOST': RDS_HOST,
        'RDS_DB_NAME': RDS_DB_NAME,
        'RDS_USERNAME': RDS_USERNAME,
        'RDS_PASSWORD': RDS_PASSWORD,
        'S3_BUCKET': S3_BUCKET
    }
    
    missing_vars = [k for k, v in required_vars.items() if not v]
    if missing_vars:
        logger.error(f"缺少必需的环境变量: {', '.join(missing_vars)}")
        send_cloudwatch_metric('BackupFailure', 1, status='Failed')
        sys.exit(1)
    
    try:
        # 生成备份文件名
        timestamp = datetime.utcnow().strftime('%Y-%m-%d-%H%M%S')
        backup_filename = f"backup-{RDS_DB_NAME}-{timestamp}.dump"
        local_file_path = f"/tmp/{backup_filename}"
        # 构建 S3 key：如果指定了前缀则使用，否则使用默认的 backups/ 路径
        date_path = datetime.utcnow().strftime('%Y/%m/%d')
        if S3_PREFIX:
            s3_key = f"{S3_PREFIX}{date_path}/{backup_filename}"
        else:
            s3_key = f"backups/{date_path}/{backup_filename}"
        
        logger.info(f"开始备份数据库: {RDS_DB_NAME} @ {RDS_HOST}")
        logger.info(f"S3 配置: bucket={S3_BUCKET}, prefix={S3_PREFIX if S3_PREFIX else '(无)'}, key={s3_key}")
        
        # 设置 PGPASSWORD 环境变量
        env = os.environ.copy()
        env['PGPASSWORD'] = RDS_PASSWORD
        
        # 构建 pg_dump 命令（使用 dump 格式）
        pg_dump_command = [
            'pg_dump',
            '-h', RDS_HOST,
            '-p', RDS_PORT,
            '-U', RDS_USERNAME,
            '-d', RDS_DB_NAME,
            '-F', 'c',  # 自定义格式（压缩的 dump 格式）
            '-f', local_file_path,
            '--no-owner',
            '--no-acl',
            '--verbose'
        ]
        
        # 执行 pg_dump
        logger.info("执行 pg_dump...")
        result = subprocess.run(
            pg_dump_command,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600  # 1 小时超时
        )
        
        if result.returncode != 0:
            error_msg = f"pg_dump 失败: {result.stderr}"
            logger.error(error_msg)
            send_cloudwatch_metric('BackupFailure', 1, status='Failed')
            send_sns_notification(
                f"RDS 备份失败 - {RDS_DB_NAME}",
                f"备份失败于 {timestamp}\n\n错误: {error_msg}\n\n标准输出: {result.stdout}"
            )
            sys.exit(1)
        
        logger.info("pg_dump 执行成功")
        
        # 上传到 S3
        logger.info(f"上传备份到 S3: s3://{S3_BUCKET}/{s3_key}")
        if not upload_to_s3(local_file_path, S3_BUCKET, s3_key):
            error_msg = "上传到 S3 失败"
            send_cloudwatch_metric('BackupFailure', 1, status='Failed')
            send_sns_notification(
                f"RDS 备份上传失败 - {RDS_DB_NAME}",
                f"备份文件生成成功，但 S3 上传失败于 {timestamp}\n\nS3 Key: {s3_key}"
            )
            sys.exit(1)
        
        # 获取文件大小
        file_size = os.path.getsize(local_file_path)
        file_size_mb = file_size / (1024 * 1024)
        
        # 发送成功指标
        send_cloudwatch_metric('BackupSuccess', 1, status='Success')
        send_cloudwatch_metric('BackupSize', file_size_mb, unit='Megabytes', status='Success')
        
        # 发送成功通知
        success_message = f"""RDS 备份成功完成

数据库: {RDS_DB_NAME}
主机: {RDS_HOST}
时间: {timestamp}
S3 位置: s3://{S3_BUCKET}/{s3_key}
文件大小: {file_size_mb:.2f} MB
"""
        logger.info(success_message)
        send_sns_notification(
            f"RDS 备份成功 - {RDS_DB_NAME}",
            success_message
        )
        
        # 清理本地文件
        try:
            os.remove(local_file_path)
            logger.info("已清理本地备份文件")
        except Exception as e:
            logger.warning(f"清理本地文件失败: {e}")
        
        logger.info("备份完成")
        
    except subprocess.TimeoutExpired:
        error_msg = "备份超时（超过 1 小时）"
        logger.error(error_msg)
        send_cloudwatch_metric('BackupFailure', 1, status='Failed')
        send_sns_notification(
            f"RDS 备份超时 - {RDS_DB_NAME}",
            f"备份超时于 {datetime.utcnow().strftime('%Y-%m-%d-%H%M%S')}\n\n{error_msg}"
        )
        sys.exit(1)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"备份失败: {error_msg}", exc_info=True)
        send_cloudwatch_metric('BackupFailure', 1, status='Failed')
        send_sns_notification(
            f"RDS 备份失败 - {RDS_DB_NAME}",
            f"备份失败于 {datetime.utcnow().strftime('%Y-%m-%d-%H%M%S')}\n\n错误: {error_msg}"
        )
        sys.exit(1)

if __name__ == '__main__':
    main()


