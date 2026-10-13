# Product Image Upload API

Backend service for uploading, listing and deleting product images by SKU. Images are stored in an external S3-compatible storage (RustFS). The storage is not part of this project. Images are served through the API, so the storage does not need to be reachable by clients.

## Requirements

- Docker with Docker Compose v2

## Configuration

Copy the example file and fill in the values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `S3_ACCESS_KEY` | Storage access key (required) |
| `S3_SECRET_KEY` | Storage secret key (required) |
| `S3_PUBLIC_ENDPOINT` | Storage URL the API connects|
| `S3_BUCKET` | Bucket name, default `local-upload-test` |
| `S3_REGION` | Default `us-east-1` |
| `API_BASE_URL` | Public URL of this API used in image links |
| `MAX_UPLOAD_BYTES` | Max upload size, default `10485760` (10 MB) |
| `CREATE_BUCKET` | Create the bucket on startup, default `true` |
| `CORS_ORIGINS` | Allowed origins as a JSON list, default `["*"]` |

Do not commit `.env`.

## Deployment

First time:

```bash
docker compose up -d --build
```

Deploy a new version:

```bash
git pull
docker compose up -d --build api
```

After changing `.env`:

```bash
docker compose up -d --force-recreate
```

Other commands:

```bash
docker compose ps              # status
docker compose logs -f api     # logs
docker compose down            # stop
```

### Ports

| Port | Service |
|---|---|
| 8000 | API |

### Health check

`GET /health` returns `200` when the API and storage are working, and `503` when storage is unreachable.

## API

API docs are available at `/docs` on the running service.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service status |
| GET | `/skus` | List SKUs with image count and cover image. Supports `limit` and `offset` |
| GET | `/skus/{sku}` | Check if a SKU has images |
| DELETE | `/skus/{sku}` | Delete a SKU and all its images |
| GET | `/skus/{sku}/images` | List images for a SKU |
| POST | `/skus/{sku}/images` | Upload an image (form-data, field `file`) |
| GET | `/skus/{sku}/images/{filename}` | View an image file |
| DELETE | `/skus/{sku}/images/{filename}` | Delete an image |

- Only JPEG and PNG, up to 10 MB.
- Image links do not expire. They load through the API.

Example:

```bash
curl -F file=@photo.jpg <API_URL>/skus/ABC123/images
```

## Production notes

- Run behind a reverse proxy with HTTPS and set an upload limit of about 11 MB (`client_max_body_size 11m` in nginx).
- Only the API needs to reach the storage address in `S3_PUBLIC_ENDPOINT`. Images are streamed through the API.
- The API has no authentication. Run it behind the internal gateway.
- Use strong storage keys and set `CORS_ORIGINS` to your frontend domains.
