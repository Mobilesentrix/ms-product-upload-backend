import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.config import get_settings


_client: BaseClient | None = None


def s3_client() -> BaseClient:
    """Shared S3 client for storage calls and signing image URLs."""
    global _client
    if _client is None:
        s = get_settings()
        _client = boto3.client(
            "s3",
            endpoint_url=s.s3_public_endpoint,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _client


def sku_prefix(sku: str) -> str:
    return f"{get_settings().upload_prefix}/{sku}/"


def image_url(key: str) -> str:
    """Link to view an image through this API (GET /skus/{sku}/images/{filename})."""
    sku, filename = key.rsplit("/", 2)[-2:]
    return f"{get_settings().api_base_url.rstrip('/')}/skus/{sku}/images/{filename}"


def ensure_bucket() -> None:
    s3 = s3_client()
    bucket = get_settings().s3_bucket
    names = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if bucket not in names:
        s3.create_bucket(Bucket=bucket)
