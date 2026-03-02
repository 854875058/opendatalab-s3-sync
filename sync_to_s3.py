"""
OpenDataLab 数据集同步到 S3 兼容对象存储

功能：将 OpenDataLab 数据集上传到 S3 兼容对象存储（MinIO / AWS S3 / 阿里云 OSS / 腾讯云 COS）

工作方式：
逐个文件处理：下载单个文件 → 上传到对象存储 → 立即删除临时文件
这样避免一次性下载整个数据集（可能几十GB），最小化磁盘占用

特点：
- 自动扫描本地数据集文件列表
- 最小化磁盘占用，临时文件立即清理
- 支持文件过滤规则
- 支持断点续传
- 支持多种 S3 兼容存储后端

注意：
由于 OpenXLab SDK 限制，无法实现真正的流式传输（直接从源到目标）
必须通过本机中转，但会最小化临时占用
"""
import os
import tempfile
import io
from datetime import datetime

try:
    from openxlab.dataset import login, download, get, info
except ImportError:
    import openxlab
    login = openxlab.login
    download = openxlab.dataset.download
    get = openxlab.dataset.get
    info = openxlab.dataset.info

from storage_backends import create_storage_backend

# ========== 配置区域（修改这里） ==========

# OpenDataLab 配置
ODL_AK = 'your-opendatalab-access-key'
ODL_SK = 'your-opendatalab-secret-key'
DATASET_REPO = 'OpenDataLab/OmniCity'  # 修改为你要同步的数据集

# 存储后端配置
STORAGE_PROVIDER = 'minio'  # 可选: 'minio', 'aws', 'oss', 'cos'
S3_ENDPOINT = 'your-storage-host:9000'
S3_AK = 'your-access-key'
S3_SK = 'your-secret-key'
S3_BUCKET = 'your-bucket-name'
S3_TARGET_PREFIX = ''  # 留空则使用数据集名称，或指定自定义前缀
S3_SECURE = False       # 是否使用 HTTPS
S3_REGION = ''          # 区域（AWS / COS 需要，如 'us-east-1' 或 'ap-guangzhou'）
S3_APPID = ''           # 仅腾讯云 COS 需要，如 '1250000000'

# 文件列表获取方式
# 'auto': 自动扫描本地已下载的数据集目录
# 'manual': 使用下面手动指定的 FILES_TO_SYNC 列表
# 'sync_all': 先下载整个数据集，然后逐个上传
# 'progressive': ⭐推荐！自动获取文件列表→逐个下载上传删除（最省空间，全自动）
FILE_LIST_MODE = 'progressive'

# 手动指定要同步的文件列表（仅在 FILE_LIST_MODE='manual' 时生效）
# 从 OpenDataLab 网站或 info 命令查看数据集包含的文件，然后配置这里
FILES_TO_SYNC = [
    'README.md',
    'metafile.yaml',
    'raw/ut-interaction_labels_110912.xls',
    'raw/ut-interaction_segmented_set1.zip',
    'raw/ut-interaction_segmented_set2.zip',
    'raw/ut-interaction_set1.zip',
    'raw/ut-interaction_set2.zip',
]

# sync_all 模式配置
DOWNLOAD_DIR = './temp_download'  # 临时下载目录
CLEAN_AFTER_SYNC = True  # 同步完成后是否删除下载的文件

# progressive 模式配置
# 注意：缓存文件会自动根据数据集名称生成，例如：
#   file_list_cache_UT-Interaction.txt
#   sync_progress_UT-Interaction.txt
FILE_LIST_CACHE_PREFIX = './file_list_cache'  # 文件列表缓存前缀
SYNC_PROGRESS_PREFIX = './sync_progress'  # 同步进度记录前缀

# 获取文件列表策略
AUTO_DOWNLOAD_FOR_LIST = False  # 是否允许自动下载数据集来获取文件列表
                                  # True: API失败时自动下载（磁盘占用大）
                                  # False: API失败时停止，提示用户使用manual模式

# 同步模式（选择一个，用于过滤上面的文件列表）
SYNC_MODE = 'all'  # 'all': 同步所有  'raw_only': 只同步raw目录  'custom': 使用自定义过滤

# 文件过滤规则（仅在 SYNC_MODE='custom' 时生效）
# 支持通配符: * 匹配任意字符, ? 匹配单个字符
INCLUDE_PATTERNS = [
    'README.md',
    'metafile.yaml',
    'raw/*.zip',      # 只同步 raw 目录下的 zip 文件
    'raw/*.xls',      # 只同步 raw 目录下的 xls 文件
]

EXCLUDE_PATTERNS = [
    'sample/*',       # 排除 sample 目录
    '*.avi',          # 排除所有 avi 文件
]

# 优化配置
MEMORY_THRESHOLD = 100 * 1024 * 1024  # 100MB，超过此大小使用临时文件
SKIP_EXISTING = True  # 是否跳过存储中已存在的文件

# ========== 核心代码（一般不需要修改） ==========

import fnmatch

def format_size(bytes_size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def get_cache_file_path(prefix):
    """
    根据数据集名称生成缓存文件路径
    例如：'./file_list_cache' + 'UT-Interaction' => './file_list_cache_UT-Interaction.txt'
    """
    dataset_name = DATASET_REPO.split('/')[-1]
    # 清理数据集名称中的特殊字符
    safe_name = dataset_name.replace('/', '_').replace('\\', '_')
    return f"{prefix}_{safe_name}.txt"


def try_get_file_list_from_api():
    """
    尝试从 OpenDataLab API 获取文件列表（不下载数据集）
    返回: (成功标志, 文件列表)

    注意:
    - 避免使用 get() 因为它会触发下载
    - info() 只返回示例文件，不是完整列表，不使用
    """
    print(f"  尝试从 API 获取文件列表（无需下载）...")

    try:
        # 方法1: 尝试使用 list_data_files（不会触发下载）
        try:
            from openxlab.dataset import list_data_files
            files = list_data_files(dataset_repo=DATASET_REPO)
            if files and len(files) > 0:
                print(f"  ✓ 通过 list_data_files 获取到 {len(files)} 个文件")
                return True, files
        except Exception as e:
            print(f"    list_data_files 不可用: {type(e).__name__}")

        # 方法2: 尝试使用 list_raw_files（不会触发下载）
        try:
            from openxlab.dataset import list_raw_files
            files = list_raw_files(dataset_repo=DATASET_REPO)
            if files and len(files) > 0:
                print(f"  ✓ 通过 list_raw_files 获取到 {len(files)} 个文件")
                return True, files
        except Exception as e:
            print(f"    list_raw_files 不可用: {type(e).__name__}")

        # 注意:
        # - 不使用 get() 因为它会立即触发下载
        # - 不使用 info() 因为它只返回示例文件（如 "Showing 8 of 19604 files"）

        print(f"  ⚠ API 方法都不可用")
        return False, []

    except Exception as e:
        print(f"  ⚠ API 获取失败: {e}")
        return False, []


def fetch_file_list_from_dataset():
    """
    获取数据集文件列表
    优先尝试 API（不下载），失败则下载数据集扫描
    返回: 文件路径列表
    """
    dataset_name = DATASET_REPO.split('/')[-1]
    local_dir = os.path.join(DOWNLOAD_DIR, f'OpenDataLab___{dataset_name}')

    # 首先检查是否已下载
    if os.path.exists(local_dir):
        print(f"  发现已下载的数据集: {local_dir}")
        print(f"  直接扫描文件列表...")
        files = []
        for root, dirs, filenames in os.walk(local_dir):
            for filename in filenames:
                rel_path = os.path.relpath(
                    os.path.join(root, filename),
                    local_dir
                ).replace('\\', '/')
                files.append(rel_path)
        return files

    # 尝试从 API 获取（不下载）
    success, files = try_get_file_list_from_api()
    if success and files:
        return files

    # API 失败，根据配置决定是否下载
    if not AUTO_DOWNLOAD_FOR_LIST:
        print(f"\n" + "="*70)
        print(f"⚠ 无法通过 API 获取文件列表")
        print(f"="*70)
        print(f"\n有三种解决方案：")
        print(f"\n方案 1（推荐）：手动指定文件列表")
        print(f"  FILE_LIST_MODE = 'manual'")
        print(f"  FILES_TO_SYNC = ['文件1', '文件2', ...]")
        print(f"  提示：访问 https://opendatalab.com 查看文件列表")
        print(f"\n方案 2：允许自动下载（磁盘占用大）")
        print(f"  AUTO_DOWNLOAD_FOR_LIST = True")
        print(f"  程序会下载数据集扫描文件列表，扫描后可手动删除")
        print(f"\n方案 3：使用辅助工具")
        print(f"  运行 get_file_list.py 查看文件列表后手动配置")
        print(f"\n{'='*70}")
        print(f"\n❌ 已停止：请选择方案后重新运行")
        return []

    # 允许自动下载
    print(f"\n{'='*70}")
    print(f"⚠ 即将下载数据集以获取文件列表")
    print(f"{'='*70}")
    print(f"下载路径: {DOWNLOAD_DIR}")
    print(f"提示: 扫描文件列表后，可手动删除该目录节省空间")
    print(f"{'='*70}\n")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    try:
        dataset = get(dataset_repo=DATASET_REPO, target_path=DOWNLOAD_DIR)
        print(f"  ✓ 数据集下载完成")
    except Exception as e:
        print(f"  ✗ 下载失败: {e}")
        return []

    # 扫描文件
    if os.path.exists(local_dir):
        files = []
        for root, dirs, filenames in os.walk(local_dir):
            for filename in filenames:
                rel_path = os.path.relpath(
                    os.path.join(root, filename),
                    local_dir
                ).replace('\\', '/')
                files.append(rel_path)

        if files:
            print(f"  ✓ 扫描到 {len(files)} 个文件")
            print(f"\n提示: 文件列表已缓存，可以删除 {DOWNLOAD_DIR} 节省空间")

        return files

    return []


def get_dataset_files():
    """
    获取数据集的文件列表
    返回: 文件路径列表
    """
    print("正在获取数据集文件列表...")

    # 模式1: 使用手动指定的列表
    if FILE_LIST_MODE == 'manual':
        print(f"  使用手动指定的文件列表（{len(FILES_TO_SYNC)} 个文件）")
        return FILES_TO_SYNC

    # 模式2: progressive - 智能渐进式同步
    if FILE_LIST_MODE == 'progressive':
        print(f"  progressive 模式：智能获取文件列表")

        # 生成数据集专属的缓存文件路径
        cache_file = get_cache_file_path(FILE_LIST_CACHE_PREFIX)
        dataset_name = DATASET_REPO.split('/')[-1]

        # 检查是否有缓存的文件列表
        if os.path.exists(cache_file):
            print(f"  发现数据集 [{dataset_name}] 的缓存: {cache_file}")
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    files = [line.strip() for line in f if line.strip()]
                print(f"  从缓存加载 {len(files)} 个文件")
                return files
            except Exception as e:
                print(f"  读取缓存失败: {e}，重新获取...")

        # 没有缓存，需要获取文件列表
        print(f"  首次同步数据集 [{dataset_name}]，获取文件列表...")
        files = fetch_file_list_from_dataset()

        # 保存文件列表到缓存
        if files:
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    for file_path in files:
                        f.write(file_path + '\n')
                print(f"  ✓ 文件列表已缓存到: {cache_file}")
                print(f"  ✓ 找到 {len(files)} 个文件")
            except Exception as e:
                print(f"  ⚠ 保存缓存失败: {e}")

        return files

    # 模式3: sync_all - 先下载数据集，获取完整文件列表
    if FILE_LIST_MODE == 'sync_all':
        print(f"  sync_all 模式：下载数据集以获取完整文件列表")

        # 检查是否已经下载过
        dataset_name = DATASET_REPO.split('/')[-1]
        local_dir = os.path.join(DOWNLOAD_DIR, f'OpenDataLab___{dataset_name}')

        if os.path.exists(local_dir):
            print(f"  发现已下载的数据集: {local_dir}")
            print(f"  直接扫描文件列表...")
        else:
            print(f"  开始下载数据集到: {DOWNLOAD_DIR}")
            print(f"  (这可能需要一些时间，取决于数据集大小)")

            # 创建下载目录
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)

            # 使用 get() 下载整个数据集
            try:
                dataset = get(dataset_repo=DATASET_REPO, target_path=DOWNLOAD_DIR)
                print(f"  ✓ 数据集下载完成")
            except Exception as e:
                print(f"  ✗ 下载失败: {e}")
                return []

        # 扫描下载的目录
        if os.path.exists(local_dir):
            print(f"  扫描文件列表...")
            files = []
            for root, dirs, filenames in os.walk(local_dir):
                for filename in filenames:
                    rel_path = os.path.relpath(
                        os.path.join(root, filename),
                        local_dir
                    ).replace('\\', '/')
                    files.append(rel_path)
            print(f"  找到 {len(files)} 个文件")
            return files
        else:
            print(f"  ✗ 未找到数据集目录")
            return []

    # 模式4: 自动扫描本地已下载的目录
    if FILE_LIST_MODE == 'auto':
        base_dir = f'./OpenDataLab___{DATASET_REPO.split("/")[1]}'
        if os.path.exists(base_dir):
            print(f"  从本地目录扫描: {base_dir}")
            files = []
            for root, dirs, filenames in os.walk(base_dir):
                for filename in filenames:
                    rel_path = os.path.relpath(
                        os.path.join(root, filename),
                        base_dir
                    ).replace('\\', '/')
                    files.append(rel_path)
            return files
        else:
            print(f"  ⚠ 未找到本地数据集目录: {base_dir}")
            print(f"  请先下载数据集，或切换到 FILE_LIST_MODE='manual'")
            return []

    return []


def should_sync_file(file_path):
    """
    根据配置判断是否应该同步该文件
    """
    # 模式：all - 同步所有
    if SYNC_MODE == 'all':
        return True

    # 模式：raw_only - 只同步 raw 目录
    if SYNC_MODE == 'raw_only':
        return file_path.startswith('raw/')

    # 模式：custom - 使用自定义过滤规则
    if SYNC_MODE == 'custom':
        # 先检查排除规则
        for pattern in EXCLUDE_PATTERNS:
            if fnmatch.fnmatch(file_path, pattern):
                return False

        # 再检查包含规则（如果没有包含规则，则默认包含所有）
        if not INCLUDE_PATTERNS:
            return True

        for pattern in INCLUDE_PATTERNS:
            if fnmatch.fnmatch(file_path, pattern):
                return True

        return False

    return True


def find_downloaded_file(tmp_dir, file_path):
    """查找下载的文件（OpenXLab 会创建子目录）"""
    possible_paths = [
        os.path.join(tmp_dir, os.path.basename(file_path)),
        os.path.join(tmp_dir, file_path),
        os.path.join(tmp_dir, f'OpenDataLab___{DATASET_REPO.split("/")[1]}', file_path),
        os.path.join(tmp_dir, f'OpenDataLab___{DATASET_REPO.split("/")[1]}', os.path.basename(file_path)),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # 遍历整个目录查找
    for root, dirs, files in os.walk(tmp_dir):
        if os.path.basename(file_path) in files:
            return os.path.join(root, os.path.basename(file_path))

    return None


def load_completed_files():
    """加载已完成的文件列表（数据集专属）"""
    progress_file = get_cache_file_path(SYNC_PROGRESS_PREFIX)
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return set(line.strip() for line in f if line.strip())
        except:
            return set()
    return set()


def mark_file_completed(file_path):
    """标记文件为已完成（数据集专属）"""
    progress_file = get_cache_file_path(SYNC_PROGRESS_PREFIX)
    try:
        with open(progress_file, 'a', encoding='utf-8') as f:
            f.write(file_path + '\n')
    except Exception as e:
        print(f"  ⚠ 记录进度失败: {e}")


def sync_file(file_path, storage, bucket, object_name, use_memory=True):
    """
    同步单个文件
    use_memory: True=内存模式，False=临时文件模式
    """
    mode = "内存处理" if use_memory else "临时文件"
    print(f"  -> 模式: {mode}")

    # progressive 模式：逐个下载上传删除
    if FILE_LIST_MODE == 'progressive':
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 下载单个文件
            print(f"  -> 下载中...")
            download(
                dataset_repo=DATASET_REPO,
                source_path=file_path,
                target_path=tmp_dir
            )

            # 查找文件
            local_file = find_downloaded_file(tmp_dir, file_path)
            if not local_file:
                raise FileNotFoundError(f"下载后未找到文件: {file_path}")

            file_size = os.path.getsize(local_file)
            print(f"  -> 下载完成: {format_size(file_size)}")

            # 上传
            if use_memory and file_size < MEMORY_THRESHOLD:
                print(f"  -> 读入内存...")
                with open(local_file, 'rb') as f:
                    file_data = io.BytesIO(f.read())
                print(f"  -> 上传中...")
                storage.put_object(bucket, object_name, file_data, length=file_size)
            else:
                print(f"  -> 上传中...")
                storage.fput_object(bucket, object_name, local_file)

            print(f"  -> 上传完成（临时文件将自动删除）")
            # tempfile.TemporaryDirectory 会自动删除临时文件
            return file_size

    # sync_all 模式：直接使用已下载的文件
    if FILE_LIST_MODE == 'sync_all':
        dataset_name = DATASET_REPO.split('/')[-1]
        local_dir = os.path.join(DOWNLOAD_DIR, f'OpenDataLab___{dataset_name}')
        local_file = os.path.join(local_dir, file_path)

        if not os.path.exists(local_file):
            raise FileNotFoundError(f"本地文件不存在: {local_file}")

        file_size = os.path.getsize(local_file)
        print(f"  -> 文件大小: {format_size(file_size)}")

        # 上传
        if use_memory and file_size < MEMORY_THRESHOLD:
            print(f"  -> 读入内存...")
            with open(local_file, 'rb') as f:
                file_data = io.BytesIO(f.read())
            print(f"  -> 上传中...")
            storage.put_object(bucket, object_name, file_data, length=file_size)
        else:
            print(f"  -> 上传中...")
            storage.fput_object(bucket, object_name, local_file)

        print(f"  -> 上传完成")
        return file_size

    # manual 和 auto 模式：需要下载文件
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 下载
        print(f"  -> 下载中...")
        download(
            dataset_repo=DATASET_REPO,
            source_path=file_path,
            target_path=tmp_dir
        )

        # 查找文件
        local_file = find_downloaded_file(tmp_dir, file_path)
        if not local_file:
            raise FileNotFoundError(f"下载后未找到文件: {file_path}")

        file_size = os.path.getsize(local_file)
        print(f"  -> 下载完成: {format_size(file_size)}")

        # 上传
        if use_memory:
            # 小文件：读入内存上传
            print(f"  -> 读入内存...")
            with open(local_file, 'rb') as f:
                file_data = io.BytesIO(f.read())
            print(f"  -> 上传中...")
            storage.put_object(bucket, object_name, file_data, length=file_size)
        else:
            # 大文件：直接上传
            print(f"  -> 上传中...")
            storage.fput_object(bucket, object_name, local_file)

        print(f"  -> 上传完成")
        return file_size


def main():
    """主函数"""
    start_time = datetime.now()

    print("="*70)
    print(f"OpenDataLab → {STORAGE_PROVIDER.upper()} 对象存储 数据同步")
    print("="*70)
    print(f"开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 1. 初始化连接
    try:
        login(ak=ODL_AK, sk=ODL_SK)
        print("✓ OpenDataLab 登录成功")

        storage = create_storage_backend(
            provider=STORAGE_PROVIDER,
            endpoint=S3_ENDPOINT,
            access_key=S3_AK,
            secret_key=S3_SK,
            secure=S3_SECURE,
            region=S3_REGION or None,
            appid=S3_APPID or None,
        )
        print(f"✓ 存储后端连接成功 ({STORAGE_PROVIDER}): {S3_ENDPOINT}")

        if not storage.bucket_exists(S3_BUCKET):
            storage.make_bucket(S3_BUCKET)
            print(f"✓ 创建 Bucket: {S3_BUCKET}")
        else:
            print(f"✓ Bucket 已存在: {S3_BUCKET}")

    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        return

    # 2. 获取文件列表
    all_files = get_dataset_files()
    if not all_files:
        print("✗ 无法获取文件列表，退出")
        return

    print(f"  数据集共有 {len(all_files)} 个文件")

    # 3. 应用过滤规则
    files_to_sync = [f for f in all_files if should_sync_file(f)]

    print(f"  根据同步模式 '{SYNC_MODE}'，筛选出 {len(files_to_sync)} 个文件")

    if not files_to_sync:
        print("✗ 没有文件需要同步")
        return

    # 加载已完成的文件（用于断点续传）
    completed_files = load_completed_files() if FILE_LIST_MODE == 'progressive' else set()
    if completed_files:
        dataset_name = DATASET_REPO.split('/')[-1]
        progress_file = get_cache_file_path(SYNC_PROGRESS_PREFIX)
        print(f"  发现数据集 [{dataset_name}] 已完成 {len(completed_files)} 个文件")
        print(f"  进度文件: {progress_file}")
        remaining = [f for f in files_to_sync if f not in completed_files]
        print(f"  剩余 {len(remaining)} 个文件待同步")

    # 确定目标前缀
    target_prefix = S3_TARGET_PREFIX if S3_TARGET_PREFIX else DATASET_REPO.split('/')[-1]
    print(f"  存储路径: {S3_BUCKET}/{target_prefix}/\n")

    # 4. 同步文件
    success_count = 0
    fail_count = 0
    skip_count = 0
    total_bytes = 0

    for idx, file_path in enumerate(files_to_sync, 1):
        # progressive 模式：检查是否已完成
        if FILE_LIST_MODE == 'progressive' and file_path in completed_files:
            skip_count += 1
            continue
        print(f"{'='*70}")
        print(f"[{idx}/{len(files_to_sync)}] {file_path}")
        print(f"{'='*70}")

        object_name = f"{target_prefix}/{file_path}".replace('\\', '/')

        try:
            # 检查是否已存在
            if SKIP_EXISTING:
                if storage.stat_object(S3_BUCKET, object_name):
                    print(f"  -> 文件已存在，跳过")
                    skip_count += 1
                    continue

            # 获取文件大小，决定用内存还是临时文件
            # 这里简单判断，也可以先下载后判断
            use_memory = 'zip' not in file_path.lower()  # zip文件用临时文件

            bytes_transferred = sync_file(
                file_path, storage, S3_BUCKET, object_name, use_memory
            )

            total_bytes += bytes_transferred
            success_count += 1
            print(f"  -> ✓ 同步成功\n")

            # progressive 模式：标记文件为已完成
            if FILE_LIST_MODE == 'progressive':
                mark_file_completed(file_path)

        except Exception as e:
            print(f"  -> ✗ 同步失败: {e}\n")
            fail_count += 1

    # 5. 总结
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(f"{'='*70}")
    print("同步完成")
    print(f"{'='*70}")
    print(f"数据集: {DATASET_REPO}")
    print(f"存储后端: {STORAGE_PROVIDER}")
    print(f"模式: {FILE_LIST_MODE} + {SYNC_MODE}")
    print(f"耗时: {duration:.1f} 秒")
    print(f"成功: {success_count} | 跳过: {skip_count} | 失败: {fail_count}")
    print(f"传输: {format_size(total_bytes)}")

    if duration > 0:
        print(f"速度: {format_size(total_bytes/duration)}/s")

    if success_count == len(files_to_sync) - skip_count:
        print("\n✓ 所有文件同步成功！")
    elif fail_count > 0:
        print(f"\n⚠ {fail_count} 个文件失败，请检查错误信息")

    # 6. 清理下载的文件（仅 sync_all 模式）
    if FILE_LIST_MODE == 'sync_all' and CLEAN_AFTER_SYNC and success_count > 0:
        import shutil
        dataset_name = DATASET_REPO.split('/')[-1]
        local_dir = os.path.join(DOWNLOAD_DIR, f'OpenDataLab___{dataset_name}')

        if os.path.exists(local_dir):
            print(f"\n清理下载的文件...")
            try:
                shutil.rmtree(local_dir)
                print(f"✓ 已删除: {local_dir}")
            except Exception as e:
                print(f"⚠ 清理失败: {e}")
                print(f"  请手动删除: {local_dir}")


if __name__ == "__main__":
    main()
