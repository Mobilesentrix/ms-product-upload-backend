import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.config import get_settings
from app.schemas import ImageItem, ImageList, SkuDeleted, SkuInfo, SkuList, SkuPath, SkuSummary
from app.storage import image_url, s3_client, sku_prefix

router = APIRouter(prefix="/skus", tags=["skus"])
log = logging.getLogger("upload-api")


def _list_objects(prefix: str) -> list[dict]:
    paginator = s3_client().get_paginator("list_objects_v2")
    objects: list[dict] = []
    for page in paginator.paginate(Bucket=get_settings().s3_bucket, Prefix=prefix):
        objects.extend(page.get("Contents", []))
    return objects


@router.get("", response_model=SkuList)
def list_skus(
    limit: int = Query(100, ge=1, le=500, description="SKUs per page"),
    offset: int = Query(0, ge=0, description="SKUs to skip"),
) -> SkuList:
    """SKUs that have images, newest upload first. `total` is the count across all pages."""
    root = f"{get_settings().upload_prefix}/"
    latest: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for obj in _list_objects(root):
        parts = obj["Key"][len(root):].split("/", 1)
        if len(parts) != 2 or not parts[1]:
            continue
        sku = parts[0]
        counts[sku] = counts.get(sku, 0) + 1
        if sku not in latest or obj["LastModified"] > latest[sku]["LastModified"]:
            latest[sku] = obj

    ordered = sorted(latest.items(), key=lambda kv: kv[1]["LastModified"], reverse=True)
    page = [
        SkuSummary(
            sku=sku,
            image_count=counts[sku],
            last_uploaded=obj["LastModified"],
            cover_url=image_url(obj["Key"]),
        )
        for sku, obj in ordered[offset : offset + limit]
    ]
    return SkuList(total=len(ordered), skus=page)


@router.get("/{sku}", response_model=SkuInfo)
def get_sku(sku: SkuPath) -> SkuInfo:
    count = len(_list_objects(sku_prefix(sku)))
    return SkuInfo(sku=sku, exists=count > 0, image_count=count)


@router.get("/{sku}/images", response_model=ImageList)
def list_images(sku: SkuPath) -> ImageList:
    """All images of one SKU, newest first."""
    objects = sorted(_list_objects(sku_prefix(sku)), key=lambda o: o["LastModified"], reverse=True)
    images = [
        ImageItem(
            key=o["Key"],
            filename=o["Key"].rsplit("/", 1)[-1],
            size=o["Size"],
            last_modified=o["LastModified"],
            url=image_url(o["Key"]),
        )
        for o in objects
    ]
    return ImageList(sku=sku, images=images)


@router.delete("/{sku}", response_model=SkuDeleted)
def delete_sku(sku: SkuPath) -> SkuDeleted:
    """Delete a SKU and all of its images."""
    keys = [o["Key"] for o in _list_objects(sku_prefix(sku))]
    if not keys:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SKU not found")

    s3 = s3_client()
    bucket = get_settings().s3_bucket
    # delete_objects accepts at most 1000 keys per call.
    for i in range(0, len(keys), 1000):
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in keys[i : i + 1000]], "Quiet": True},
        )
    return SkuDeleted(sku=sku, deleted=len(keys))
