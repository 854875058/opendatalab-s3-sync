"""
存储后端抽象层

支持多种 S3 兼容对象存储：MinIO、AWS S3、阿里云 OSS、腾讯云 COS
通过统一接口调用，主脚本无需关心底层存储差异
"""
from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """存储后端抽象基类"""

    @abstractmethod
    def bucket_exists(self, bucket: str) -> bool:
        """检查 bucket 是否存在"""

    @abstractmethod
    def make_bucket(self, bucket: str) -> None:
        """创建 bucket"""

    @abstractmethod
    def stat_object(self, bucket: str, object_name: str) -> bool:
        """检查对象是否存在，返回布尔值"""

    @abstractmethod
    def put_object(self, bucket: str, object_name: str, data, length: int) -> None:
        """从内存数据上传对象"""

    @abstractmethod
    def fput_object(self, bucket: str, object_name: str, file_path: str) -> None:
        """从本地文件上传对象"""


# ========== MinIO 后端 ==========

class MinioBackend(StorageBackend):
    """MinIO 存储后端"""

    def __init__(self, endpoint, access_key, secret_key, secure=False, **kwargs):
        try:
            from minio import Minio
        except ImportError:
            raise ImportError(
                "未安装 MinIO SDK，请运行：pip install minio>=7.1.0"
            )
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def bucket_exists(self, bucket: str) -> bool:
        return self._client.bucket_exists(bucket)

    def make_bucket(self, bucket: str) -> None:
        self._client.make_bucket(bucket)

    def stat_object(self, bucket: str, object_name: str) -> bool:
        try:
            self._client.stat_object(bucket, object_name)
            return True
        except Exception:
            return False

    def put_object(self, bucket: str, object_name: str, data, length: int) -> None:
        self._client.put_object(bucket, object_name, data, length)

    def fput_object(self, bucket: str, object_name: str, file_path: str) -> None:
        self._client.fput_object(bucket, object_name, file_path)


# ========== AWS S3 后端 ==========

class AwsS3Backend(StorageBackend):
    """AWS S3 存储后端（也兼容其他 S3 API 服务）"""

    def __init__(self, endpoint, access_key, secret_key, secure=True, region=None, **kwargs):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "未安装 AWS SDK，请运行：pip install boto3>=1.26.0"
            )
        protocol = "https" if secure else "http"
        endpoint_url = f"{protocol}://{endpoint}" if endpoint else None
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "us-east-1",
        )

    def bucket_exists(self, bucket: str) -> bool:
        try:
            self._client.head_bucket(Bucket=bucket)
            return True
        except Exception:
            return False

    def make_bucket(self, bucket: str) -> None:
        self._client.create_bucket(Bucket=bucket)

    def stat_object(self, bucket: str, object_name: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=object_name)
            return True
        except Exception:
            return False

    def put_object(self, bucket: str, object_name: str, data, length: int) -> None:
        data.seek(0)
        self._client.put_object(Bucket=bucket, Key=object_name, Body=data.read())

    def fput_object(self, bucket: str, object_name: str, file_path: str) -> None:
        self._client.upload_file(file_path, bucket, object_name)


# ========== 阿里云 OSS 后端 ==========

class AliyunOssBackend(StorageBackend):
    """阿里云 OSS 存储后端"""

    def __init__(self, endpoint, access_key, secret_key, **kwargs):
        try:
            import oss2
        except ImportError:
            raise ImportError(
                "未安装阿里云 OSS SDK，请运行：pip install oss2>=2.17.0"
            )
        self._oss2 = oss2
        self._auth = oss2.Auth(access_key, secret_key)
        self._endpoint = endpoint if endpoint.startswith("http") else f"https://{endpoint}"
        self._bucket_cache: dict = {}

    def _get_bucket(self, bucket: str):
        if bucket not in self._bucket_cache:
            self._bucket_cache[bucket] = self._oss2.Bucket(
                self._auth, self._endpoint, bucket
            )
        return self._bucket_cache[bucket]

    def bucket_exists(self, bucket: str) -> bool:
        try:
            self._get_bucket(bucket).get_bucket_info()
            return True
        except Exception:
            return False

    def make_bucket(self, bucket: str) -> None:
        self._get_bucket(bucket).create_bucket()

    def stat_object(self, bucket: str, object_name: str) -> bool:
        try:
            self._get_bucket(bucket).head_object(object_name)
            return True
        except Exception:
            return False

    def put_object(self, bucket: str, object_name: str, data, length: int) -> None:
        data.seek(0)
        self._get_bucket(bucket).put_object(object_name, data)

    def fput_object(self, bucket: str, object_name: str, file_path: str) -> None:
        self._get_bucket(bucket).put_object_from_file(object_name, file_path)


# ========== 腾讯云 COS 后端 ==========

class TencentCosBackend(StorageBackend):
    """腾讯云 COS 存储后端"""

    def __init__(self, endpoint, access_key, secret_key, region=None, appid=None, **kwargs):
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError:
            raise ImportError(
                "未安装腾讯云 COS SDK，请运行：pip install cos-python-sdk-v5>=1.9.0"
            )
        self._appid = appid or ""
        scheme = "https"
        # endpoint 示例: cos.ap-guangzhou.myqcloud.com 或 ap-guangzhou
        if region:
            actual_region = region
        elif endpoint:
            # 尝试从 endpoint 提取 region
            parts = endpoint.replace("https://", "").replace("http://", "").split(".")
            actual_region = parts[0].replace("cos.", "") if len(parts) > 1 else endpoint
        else:
            actual_region = "ap-guangzhou"

        config = CosConfig(
            Region=actual_region,
            SecretId=access_key,
            SecretKey=secret_key,
            Scheme=scheme,
        )
        self._client = CosS3Client(config)

    def _full_bucket_name(self, bucket: str) -> str:
        """COS 的 bucket 名称需要拼接 APPID，例如 mybucket-1250000000"""
        if self._appid and not bucket.endswith(f"-{self._appid}"):
            return f"{bucket}-{self._appid}"
        return bucket

    def bucket_exists(self, bucket: str) -> bool:
        try:
            self._client.head_bucket(Bucket=self._full_bucket_name(bucket))
            return True
        except Exception:
            return False

    def make_bucket(self, bucket: str) -> None:
        self._client.create_bucket(Bucket=self._full_bucket_name(bucket))

    def stat_object(self, bucket: str, object_name: str) -> bool:
        try:
            self._client.head_object(
                Bucket=self._full_bucket_name(bucket), Key=object_name
            )
            return True
        except Exception:
            return False

    def put_object(self, bucket: str, object_name: str, data, length: int) -> None:
        data.seek(0)
        self._client.put_object(
            Bucket=self._full_bucket_name(bucket),
            Key=object_name,
            Body=data,
        )

    def fput_object(self, bucket: str, object_name: str, file_path: str) -> None:
        self._client.upload_file(
            Bucket=self._full_bucket_name(bucket),
            Key=object_name,
            LocalFilePath=file_path,
        )


# ========== 工厂函数 ==========

_BACKENDS = {
    "minio": MinioBackend,
    "aws": AwsS3Backend,
    "oss": AliyunOssBackend,
    "cos": TencentCosBackend,
}


def create_storage_backend(
    provider: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool = False,
    region: str = None,
    appid: str = None,
) -> StorageBackend:
    """
    根据 provider 创建对应的存储后端实例

    参数:
        provider: 存储提供商 ('minio', 'aws', 'oss', 'cos')
        endpoint: 服务端点地址
        access_key: 访问密钥
        secret_key: 密钥
        secure: 是否使用 HTTPS (MinIO/AWS)
        region: 区域 (AWS/COS 需要)
        appid: 应用 ID (仅 COS 需要)

    返回:
        StorageBackend 实例
    """
    provider = provider.lower().strip()
    if provider not in _BACKENDS:
        supported = ", ".join(_BACKENDS.keys())
        raise ValueError(
            f"不支持的存储提供商: '{provider}'，支持的选项: {supported}"
        )

    backend_cls = _BACKENDS[provider]
    return backend_cls(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=region,
        appid=appid,
    )
