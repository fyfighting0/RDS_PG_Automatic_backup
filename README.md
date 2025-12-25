# RDS PostgreSQL 自动备份到 S3

使用 AWS ECS Fargate 和 Scheduled Tasks 自动备份 RDS PostgreSQL 数据库到 S3。

## 功能特性

- 自动定时备份 PostgreSQL 数据库
- 备份文件上传到 S3
- SNS 邮件通知（成功/失败）
- ECS Scheduled Tasks 定时触发

## 快速开始

### 1. 构建 Docker 镜像

```bash
docker build -t rds-backup:latest .
```

### 2. 推送到 ECR

```bash
# 替换为你的 ECR 地址
aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.ap-northeast-1.amazonaws.com
docker tag rds-backup:latest YOUR_ACCOUNT_ID.dkr.ecr.ap-northeast-1.amazonaws.com/rds-backup:latest
docker push YOUR_ACCOUNT_ID.dkr.ecr.ap-northeast-1.amazonaws.com/rds-backup:latest
```

### 3. 配置环境变量

| 环境变量 | 说明 | 示例 |
|---|---|---|
| `RDS_HOST` | RDS 端点 | `mydb.xxxxx.rds.amazonaws.com` |
| `RDS_PORT` | 数据库端口 | `5432` |
| `RDS_DB_NAME` | 数据库名称 | `postgres` |
| `RDS_USERNAME` | 数据库用户名 | `postgres` |
| `RDS_PASSWORD` | 数据库密码 | 
| `S3_BUCKET` | S3 存储桶名称 | `my-bucket`|
| `SNS_TOPIC_ARN` | SNS Topic ARN | `arn:aws:sns:region:account-id:topic-name` |
| `CLOUDWATCH_NAMESPACE` | CloudWatch 命名空间 | `RDS/Backup` |
| `AWS_REGION` | AWS 区域 | `ap-northeast-1` |

### 4. 在 ECS 中部署

1. 创建 ECS 任务定义，配置环境变量
2. 在 ECS 控制台的 **Scheduled Tasks** 中创建定时任务
3. 配置 Cron 表达式（如：`cron(0 0 * * ? *)` 每日凌晨执行）

## 备份文件位置

备份文件存储在 S3：
```
s3://<bucket-name>/backups/YYYY/MM/DD/backup-<db-name>-<timestamp>.dump
```
