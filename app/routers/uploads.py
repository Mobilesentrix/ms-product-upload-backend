import logging
from datetime import datetime, timezone
from uuid import uuid4

from botocore.exceptions import ClientError
from fastapi import APIRouter, File, HTTPException, Path, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.config import get_settings
from app.schemas import ImageItem, SkuPath
from app.storage import s3_client, sku_prefix

router = APIRouter(prefix="/skus", tags=["images"])
log = logging.getLogger("upload-api")

# Detect the real image type from the file's first bytes, not the name or header.
SIGNATURES = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
}


def _detect_type(data: bytes) -> tuple[str, str] | None:
    for magic, info in SIGNATURES.items():
        if data.startswith(magic):
            return info
    return None


@router.post("/{sku}/images", response_model=ImageItem, status_code=status.HTTP_201_CREATED)
async def upload_image(sku: SkuPath, file: UploadFile = File(..., description="JPEG or PNG image")) -> ImageItem:
    """Upload one image for a SKU as multipart/form-data (field name: `file`)."""
    s = get_settings()
    sku = sku.upper()

    data = await file.read(s.max_upload_bytes + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
    if len(data) > s.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is larger than {s.max_upload_bytes // (1024 * 1024)} MB",
        )

    detected = _detect_type(data)
    if detected is None or detected[0] not in s.allowed_content_types:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Only {', '.join(s.allowed_content_types)} images are allowed",
        )
    content_type, ext = detected

    stamp = datetime.now(timezone.utc)
    filename = f"{stamp:%Y-%m-%d_%H-%M-%S}_{uuid4().hex[:8]}.{ext}"
    key = f"{sku_prefix(sku)}{filename}"

    # boto3 is blocking; run it off the event loop so other requests keep flowing.
    await run_in_threadpool(
        s3_client().put_object, Bucket=s.s3_bucket, Key=key, Body=data, ContentType=content_type
    )

    url = s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": s.s3_bucket, "Key": key},
        ExpiresIn=s.view_url_expires,
    )
    log.info("Uploaded key=%s size=%d type=%s", key, len(data), content_type)
    log.info("Image URL: %s", url)
    return ImageItem(key=key, filename=filename, size=len(data), last_modified=stamp, url=url)


@router.delete("/{sku}/images/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(sku: SkuPath, filename: str = Path(pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}$")) -> None:
    s = get_settings()
    key = f"{sku_prefix(sku.upper())}{filename}"
    s3 = s3_client()
    try:
        s3.head_object(Bucket=s.s3_bucket, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found") from None
        raise
    s3.delete_object(Bucket=s.s3_bucket, Key=key)
