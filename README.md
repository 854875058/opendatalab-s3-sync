# OpenDataLab S3 Sync

将 [OpenDataLab](https://opendatalab.com) 开放数据集同步到 S3 兼容对象存储的 Python 工具。

支持 **MinIO** / **AWS S3** / **阿里云 OSS** / **腾讯云 COS**。

## 解决什么问题

在企业内网环境中，直接访问公网数据集平台不方便或不稳定。这个工具可以把 OpenDataLab 上的数据集逐文件同步到你的对象存储中，适合：

- 内网 AI 训练环境需要使用公开数据集
- 需要将数据集统一管理到私有对象存储
- 大数据集需要断点续传、避免磁盘爆炸

## 特性

- **多存储后端** — 支持 MinIO、AWS S3、阿里云 OSS、腾讯云 COS
- **逐文件处理** — 下载单个文件 → 上传存储 → 删除临时文件，最小化磁盘占用
- **断点续传** — 自动跳过已同步的文件，中断后重新运行即可继续
- **多种同步模式** — progressive（推荐）、sync_all、manual、auto
- **灵活过滤** — 支持通配符的 include/exclude 规则
- **多数据集友好** — 每个数据集独立的缓存和进度文件，互不干扰

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt

# 根据你使用的存储后端，安装对应 SDK：
pip install minio>=7.1.0              # MinIO
pip install boto3>=1.26.0             # AWS S3
pip install oss2>=2.17.0              # 阿里云 OSS
pip install cos-python-sdk-v5>=1.9.0  # 腾讯云 COS
```

### 2. 配置

编辑 `sync_to_s3.py` 顶部的配置区域。以下是各存储后端的配置示例：

#### MinIO

```python
STORAGE_PROVIDER = 'minio'
S3_ENDPOINT = 'your-minio-host:9000'
S3_AK = 'your-minio-access-key'
S3_SK = 'your-minio-secret-key'
S3_BUCKET = 'your-bucket-name'
S3_SECURE = False
```

#### AWS S3

```python
STORAGE_PROVIDER = 'aws'
S3_ENDPOINT = 's3.amazonaws.com'
S3_AK = 'your-aws-access-key-id'
S3_SK = 'your-aws-secret-access-key'
S3_BUCKET = 'your-bucket-name'
S3_SECURE = True
S3_REGION = 'us-east-1'
```

#### 阿里云 OSS

```python
STORAGE_PROVIDER = 'oss'
S3_ENDPOINT = 'oss-cn-hangzhou.aliyuncs.com'
S3_AK = 'your-oss-access-key-id'
S3_SK = 'your-oss-access-key-secret'
S3_BUCKET = 'your-bucket-name'
```

#### 腾讯云 COS

```python
STORAGE_PROVIDER = 'cos'
S3_ENDPOINT = 'cos.ap-guangzhou.myqcloud.com'
S3_AK = 'your-cos-secret-id'
S3_SK = 'your-cos-secret-key'
S3_BUCKET = 'your-bucket-name'
S3_REGION = 'ap-guangzhou'
S3_APPID = '1250000000'  # 你的 APPID
```

### 3. 运行

```bash
# 推荐：渐进式同步（自动获取文件列表，逐个下载上传）
python sync_to_s3.py

# 或者先查看文件列表再决定同步哪些
python get_file_list.py
```

## 同步模式

| 模式 | 说明 | 磁盘占用 | 适用场景 |
|------|------|---------|---------|
| `progressive` | 智能渐进式，逐个文件处理 | 最小（单文件大小） | 大多数场景（推荐） |
| `sync_all` | 先下载整个数据集再上传 | 大（完整数据集） | 磁盘充足、网络不稳定 |
| `manual` | 手动指定文件列表 | 最小（单文件大小） | 只需部分文件 |
| `auto` | 扫描本地已下载的目录 | 0（已下载） | 已有本地数据集 |

## 文件过滤

```python
SYNC_MODE = 'custom'

INCLUDE_PATTERNS = [
    'raw/*.zip',      # 只要 zip 文件
    'README.md',
]

EXCLUDE_PATTERNS = [
    'sample/*',       # 排除 sample 目录
    '*.avi',          # 排除视频文件
]
```

## 大数据集处理

对于超大数据集（>50GB），推荐分批手动同步：

```bash
# 1. 先查看文件列表
python get_file_list.py

# 2. 将输出的文件列表复制到 sync_to_s3.py，分批配置 FILES_TO_SYNC
# 3. 每批运行一次 python sync_to_s3.py
```

## 项目结构

```
.
├── sync_to_s3.py          # 主同步脚本（支持多存储后端）
├── storage_backends.py    # 存储后端抽象层（MinIO/AWS/OSS/COS）
├── get_file_list.py       # 文件列表查询工具（不下载数据）
├── sync_to_minio.py       # 旧版脚本（仅 MinIO，保留兼容）
├── requirements.txt       # Python 依赖
└── README.md
```

## License

MIT
