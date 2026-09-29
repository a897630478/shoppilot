# backend/core/storage.py
# MinIO 商品图片存取（桶幂等创建；凭证/端点全部来自 .env.local）
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=False,   # 本地 docker http
        )
    return _client


def ensure_bucket() -> None:
    bucket = get_settings().minio_bucket
    client = _get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("storage.bucket_created", bucket=bucket)


def upload_product_image(object_name: str, data: bytes, content_type: str) -> str:
    from io import BytesIO
    bucket = get_settings().minio_bucket
    _get_client().put_object(
        bucket, object_name, BytesIO(data), len(data),
        content_type=content_type,
    )
    return object_name


def download_product_image(object_name: str) -> tuple[bytes, str]:
    bucket = get_settings().minio_bucket
    try:
        resp = _get_client().get_object(bucket, object_name)
    except S3Error as e:
        if e.code in ("NoSuchKey", "NoSuchObject"):
            raise FileNotFoundError(object_name) from e
        raise
    try:
        return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")
    finally:
        resp.close()
        resp.release_conn()


def presign_image_url(object_name: str, expires_seconds: int = 900) -> str | None:
    """生成商品图片预签名 URL（浏览器 <img> 直连 MinIO；桶保持私有）。

    默认 15 分钟有效。对象不存在或 MinIO 异常时返回 None，调用方降级为无图。
    """
    if not object_name:
        return None
    try:
        bucket = get_settings().minio_bucket
        return _get_client().presigned_get_object(
            bucket, object_name, expires=timedelta(seconds=expires_seconds))
    except Exception as e:
        logger.warning("storage.presign_failed", object=object_name, error=str(e))
        return None
