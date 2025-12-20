# Troutlytics WA API

FastAPI service that exposes Washington trout stocking data. Reads shared SQLAlchemy models in `data/` and can run as a Lambda function (via Mangum) or a containerized service.

## Requirements

- Python 3.11+
- Database credentials supplied via environment variables
- Docker (for the Compose setup)

## Configuration

The API expects database settings in the environment (Compose reads from `.env`):

| Variable                                        | Purpose                                |
| :---------------------------------------------- | :------------------------------------- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`            | Credentials for Aurora/PostgreSQL      |
| `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT` | Connection target (defaults to `5432`) |

If any values are missing, the service falls back to `data/sqlite.db` for read-only local use.

## Run Locally

### Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r api/requirements.txt
uvicorn api.index:app --reload --port 8080
```

Set the database environment variables before starting the server. Open `http://localhost:8080/docs` for the Swagger UI.

### Docker Compose

```bash
docker compose up api-dev
```

This builds from `api/dockerfiles/dev/Dockerfile`, loads environment variables from `.env`, and serves on `localhost:8080`.

## Deployment

- `api/dockerfiles/prod/Dockerfile` plus `lambda_entry_script.sh` produce the Lambda-compatible image.
- `handler = Mangum(app)` enables API Gateway → Lambda integration without code changes.
- Logs are emitted via the standard Python logger at INFO level.

## REST Endpoints

Unless specified, endpoints accept optional ISO 8601 `start_date` and `end_date` query parameters. Defaults use the last 7 days ending at the current time.

- `GET /`: Service metadata and route list.
- `GET /stocked_lakes_data`: Individual stocking records joined with lake locations.
- `GET /total_stocked_by_date_data`: Totals by stocking date for the requested window.
- `GET /hatchery_totals`: Totals per hatchery, ordered descending.
- `GET /derby_lakes_data`: Full `derby_participant` table.
- `GET /date_data_updated`: Timestamp of the most recent ETL write.
- `GET /hatchery_names`: Sorted list of distinct hatchery names.

On database errors, endpoints return `{ "error": "<message>" }` with HTTP 200 so polling clients can surface issues without failing their jobs.

## Contact

- Developer: Thomas Basham
- Email: bashamtg@gmail.com
