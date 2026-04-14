<div align="center">

# OpenDataLab S3 Sync

**OpenDataLab 数据集同步工具**

*Progressive dataset sync from OpenDataLab to any S3-compatible object storage with minimal disk footprint*

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python)](https://python.org/)
[![MinIO](https://img.shields.io/badge/MinIO-Object_Storage-C72E49?logo=minio)](https://min.io/)
[![AWS S3](https://img.shields.io/badge/AWS-S3-FF9900?logo=amazons3)](https://aws.amazon.com/s3/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Overview

AI 训练数据集动辄数百 GB，从 OpenDataLab 下载后再上传到私有存储，磁盘占用翻倍、传输效率低下。

本工具实现了 **渐进式同步**：逐文件下载 → 上传 → 立即删除本地副本，全程磁盘占用不超过单个文件大小。支持 MinIO、AWS S3、阿里云 OSS、腾讯云 COS 四大存储后端，通过工厂模式统一抽象。内置断点续传、通配符过滤、进度缓存，大规模数据集同步一条命令搞定。

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenDataLab API                         │
├─────────────────────────────────────────────────────────────┤
│              Progressive Sync Engine (Python)                 │
│         Download → Upload → Delete → Next File                │
├──────────┬──────────┬──────────┬────────────────────────────┤
│  MinIO   │  AWS S3  │ Aliyun   │  Tencent COS               │
│          │          │  OSS     │                              │
└──────────┴──────────┴──────────┴────────────────────────────┘
```

## Key Features

### Progressive Sync Mode
逐文件处理：下载单个文件 → 上传到目标存储 → 立即删除本地副本。磁盘占用始终保持在单文件级别，适合磁盘空间有限的环境。

### Multi-Backend Storage
通过工厂模式统一抽象四大存储后端，切换存储只需修改配置参数，业务代码零改动。

| Backend | SDK | 认证方式 |
|---------|-----|----------|
| MinIO | `minio` | Access Key + Secret Key |
| AWS S3 | `boto3` | IAM / Access Key |
| Aliyun OSS | `oss2` | Access Key + Secret Key |
| Tencent COS | `cos-python-sdk-v5` | Secret ID + Secret Key |

### Resume & Deduplication
内置缓存文件记录已同步文件列表，中断后重启自动跳过已完成文件。支持按数据集自动命名缓存文件。

### Flexible Filtering
支持 include/exclude 通配符模式过滤，精确控制同步范围。例如只同步 `.parquet` 文件或排除 `.zip` 大文件。

### Multiple Sync Modes

| Mode | Description |
|------|-------------|
| `progressive` | 逐文件下载上传删除（默认，最省磁盘） |
| `sync_all` | 先全量下载再批量上传 |
| `manual` | 仅下载到本地，手动上传 |
| `auto` | 根据磁盘空间自动选择模式 |

## Tech Stack

```
Core                              Storage SDKs                     Utilities
─────────────────                 ─────────────────               ─────────────────
Python 3                          minio (MinIO)                   OpenXLab SDK
requests (HTTP)                   boto3 (AWS S3)                  PyYAML (Config)
pathlib (File Ops)                oss2 (Aliyun OSS)               urllib3 (HTTP)
                                  cos-python-sdk-v5 (Tencent)
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        sync_to_s3.py                              │
│                    (Main Sync Orchestrator)                        │
│                                                                    │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────┐   │
│  │ OpenXLab    │    │  Progressive │    │   Cache Manager    │   │
│  │ SDK Client  │───▶│  Sync Loop   │───▶│   (Resume/Skip)    │   │
│  └─────────────┘    └──────┬───────┘    └────────────────────┘   │
│                            │                                       │
│                    ┌───────▼────────┐                              │
│                    │ storage_       │                              │
│                    │ backends.py    │                              │
│                    │ (Factory)      │                              │
│                    └───────┬────────┘                              │
│           ┌────────┬───────┼────────┬──────────┐                  │
│      ┌────▼───┐┌───▼──┐┌──▼───┐┌───▼─────┐                      │
│      │ MinIO  ││ S3   ││ OSS  ││  COS    │                      │
│      └────────┘└──────┘└──────┘└─────────┘                      │
└──────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/854875058/opendatalab-s3-sync.git
cd opendatalab-s3-sync

# 2. Install dependencies
pip install -r requirements.txt

# 3. Sync dataset to MinIO
python sync_to_s3.py \
  --dataset "OpenDataLab/COCO_2017" \
  --backend minio \
  --endpoint "localhost:9000" \
  --access-key "minioadmin" \
  --secret-key "minioadmin" \
  --bucket "datasets"

# 4. Or just list files without downloading
python get_file_list.py --dataset "OpenDataLab/COCO_2017"
```

## Project Structure

```
opendatalab-s3-sync/
├── sync_to_s3.py              # Main sync orchestrator (multi-backend)
├── storage_backends.py        # Abstract storage layer (4 backends)
├── get_file_list.py           # Dataset file list query utility
├── sync_to_minio.py           # Legacy MinIO-only version
├── requirements.txt           # Python dependencies
└── LICENSE
```

## Usage

| Command | Description |
|---------|-------------|
| `python sync_to_s3.py --dataset <name> --backend minio` | 同步到 MinIO |
| `python sync_to_s3.py --dataset <name> --backend s3` | 同步到 AWS S3 |
| `python sync_to_s3.py --dataset <name> --backend oss` | 同步到阿里云 OSS |
| `python sync_to_s3.py --dataset <name> --backend cos` | 同步到腾讯云 COS |
| `python get_file_list.py --dataset <name>` | 查询数据集文件列表 |

### Key Options

| Option | Description |
|--------|-------------|
| `--mode progressive` | 渐进式同步（默认） |
| `--include "*.parquet"` | 只同步匹配文件 |
| `--exclude "*.zip"` | 排除匹配文件 |
| `--bucket <name>` | 目标存储桶 |
| `--prefix <path>` | 目标路径前缀 |

## License

MIT
