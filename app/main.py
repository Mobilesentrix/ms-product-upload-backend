import logging
from contextlib import asynccontextmanager

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import health, skus, uploads
from app.storage import ensure_bucket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("upload-api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    log.info("Storage endpoint=%s bucket=%s region=%s", s.s3_public_endpoint, s.s3_bucket, s.s3_region)
    if get_settings().create_bucket:
        try:
            ensure_bucket()
        except (BotoCoreError, ClientError):
            log.exception("Could not ensure bucket exists; continuing")
    yield


app = FastAPI(title="Image Upload API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Reject oversized uploads from the Content-Length header, before the body is read.
# Extra 1 MB covers multipart boundaries and headers around the file.
@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    length = request.headers.get("content-length")
    limit = get_settings().max_upload_bytes + 1024 * 1024
    if length and length.isdigit() and int(length) > limit:
        return JSONResponse(
            status_code=413,
            content={"detail": f"File is larger than {get_settings().max_upload_bytes // (1024 * 1024)} MB"},
        )
    return await call_next(request)


@app.exception_handler(BotoCoreError)
@app.exception_handler(ClientError)
async def storage_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Storage error", exc_info=exc)
    return JSONResponse(status_code=502, content={"detail": "Storage is unavailable"})


app.include_router(health.router)
app.include_router(skus.router)
app.include_router(uploads.router)
