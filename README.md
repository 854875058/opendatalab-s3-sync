# OpenDataLab to MinIO Sync

将 [OpenDataLab](https://opendatalab.com) 开放数据集同步到内网 MinIO 对象存储的 Python 工具。

## 解决什么问题

在企业内网环境中，直接访问公网数据集平台不方便或不稳定。这个工具可以把 OpenDataLab 上的数据集逐文件同步到你的 MinIO 存储中，适合：

- 内网 AI 训练环境需要使用公开数据集
- 需要将数据集统一管理到私有对象存储
- 大数据集需要断点续传、避免磁盘爆炸

## 特性

- **逐文件处理** — 下载单个文件 → 上传 MinIO → 删除临时文件，最小化磁盘占用
- **断点续传** — 自动跳过已同步的文件，中断后重新运行即可继续
- **多种同步模式** — progressive（推荐）、sync_all、manual、auto
- **灵活过滤** — 支持通配符的 include/exclude 规则
- **多数据集友好** — 每个数据集独立的缓存和进度文件，互不干扰

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `sync_to_minio.py` 顶部的配置区域：

```python
# OpenDataLab 配置（在 opendatalab.com 注册获取）
ODL_AK = 'your-opendatalab-access-key'
ODL_SK = 'your-opendatalab-secret-key'
DATASET_REPO = 'OpenDataLab/COCO'  # 要同步的数据集

# MinIO 配置
MINIO_ENDPOINT = 'your-minio-host:9000'
MINIO_AK = 'your-minio-access-key'
MINIO_SK = 'your-minio-secret-key'
MINIO_BUCKET = 'your-bucket-name'
```

### 3. 运行

```bash
# 推荐：渐进式同步（自动获取文件列表，逐个下载上传）
python sync_to_minio.py

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

# 2. 将输出的文件列表复制到 sync_to_minio.py，分批配置 FILES_TO_SYNC
# 3. 每批运行一次 python sync_to_minio.py
```

## 项目结构

```
.
├── sync_to_minio.py    # 主同步脚本
├── get_file_list.py    # 文件列表查询工具（不下载数据）
├── requirements.txt    # Python 依赖
└── README.md
```

## License

MIT
