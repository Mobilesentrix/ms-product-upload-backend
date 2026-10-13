import logging
from datetime import datetime, timezone
from uuid import uuid4

from botocore.exceptions import ClientError
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.schemas import FilenamePath, ImageItem, SkuPath
from app.storage import image_url, s3_client, sku_prefix

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


def _is_not_found(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound")


@router.post("/{sku}/images", response_model=ImageItem, status_code=status.HTTP_201_CREATED)
async def upload_image(sku: SkuPath, file: UploadFile = File(..., description="JPEG or PNG image")) -> ImageItem:
    """Upload one image for a SKU as multipart/form-data (field name: `file`)."""
    s = get_settings()

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

    log.info("Uploaded key=%s size=%d type=%s", key, len(data), content_type)
    return ImageItem(key=key, filename=filename, size=len(data), last_modified=stamp, url=image_url(key))


@router.get("/{sku}/images/{filename}", response_class=StreamingResponse)
def get_image(sku: SkuPath, filename: FilenamePath) -> StreamingResponse:
    """Image file, read from storage by the API and streamed to the client."""
    s = get_settings()
    key = f"{sku_prefix(sku)}{filename}"
    try:
        obj = s3_client().get_object(Bucket=s.s3_bucket, Key=key)
    except ClientError as e:
        if _is_not_found(e):
            log.info("Image not found key=%s", key)
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found") from None
        raise
    return StreamingResponse(
        obj["Body"].iter_chunks(64 * 1024),
        media_type=obj.get("ContentType", "application/octet-stream"),
        headers={
            "Content-Length": str(obj["ContentLength"]),
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.delete("/{sku}/images/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(sku: SkuPath, filename: FilenamePath) -> None:
    s = get_settings()
    key = f"{sku_prefix(sku)}{filename}"
    s3 = s3_client()
    try:
        s3.head_object(Bucket=s.s3_bucket, Key=key)
    except ClientError as e:
        if _is_not_found(e):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found") from None
        raise
    s3.delete_object(Bucket=s.s3_bucket, Key=key)
