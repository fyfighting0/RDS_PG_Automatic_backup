FROM python:3.11-slim

# 安装 PostgreSQL 客户端工具
RUN apt-get update && \
    apt-get install -y postgresql-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir boto3

# 设置工作目录
WORKDIR /app

# 复制备份脚本
COPY backup.py /app/backup.py
RUN chmod +x /app/backup.py

# 设置入口点
ENTRYPOINT ["python3", "/app/backup.py"]


