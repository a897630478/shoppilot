# tests/test_storage.py
# 需要 docker-compose 的 minio 服务已启动
from backend.core import storage


def test_upload_download_roundtrip():
    storage.ensure_bucket()
    payload = b"\x89PNG\r\n\x1a\nfake"
    object_name = "test/roundtrip.png"
    returned = storage.upload_product_image(object_name, payload, "image/png")
    assert returned == object_name
    data, ctype = storage.download_product_image(object_name)
    assert data == payload
    assert ctype == "image/png"


def test_download_missing_raises():
    storage.ensure_bucket()
    try:
        storage.download_product_image("no/such/object.png")
        raise AssertionError("should raise FileNotFoundError")
    except FileNotFoundError:
        pass
