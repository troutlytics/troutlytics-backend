# Troutlytics Backend

Backend data platform for Troutlytics.

This repository does two things:

1. Scrapes Washington Department of Fish and Wildlife (WDFW) trout stocking reports.
2. Serves cleaned stocking data through a FastAPI service for dashboards, maps, and analytics.

## Project Links

- Website: https://troutlytics.com
- Backend repository: https://github.com/troutlytics/troutlytics-backend
- API base URL: https://xtczssso08.execute-api.us-west-2.amazonaws.com

## Problem This Project Solves

WDFW stocking information is published as a human-readable web table, but product features need a reliable machine-readable dataset. The raw source is hard to query over time, aggregate by hatchery/date, and map consistently.

This backend solves that by:

1. Extracting the source table on a schedule.
2. Normalizing and deduplicating stocking rows.
3. Resolving water bodies to stable location records.
4. Persisting curated data in a queryable database.
5. Exposing API endpoints with caching/ETag support for fast client reads.

## How It Works

1. `web_scraper/scraper.py` fetches WDFW trout plant rows (`items_per_page=250`), parses fields, and normalizes names/date/values.
2. The scraper matches each row to existing `water_location` records (exact + relaxed matching) to avoid duplicates.
3. If enabled, it can create missing water locations and optionally geocode them with Google Geocoding.
4. `data/database.py` writes `stocking_report` entries with dedupe/upsert logic and records run metadata in `utility`.
5. `api/index.py` serves raw and aggregate endpoints from the same shared models in `data/`.

## Repository Layout

```text
.
├── api/                    FastAPI app (local Uvicorn + Lambda via Mangum)
├── web_scraper/            WDFW scraper and parser
├── data/                   SQLAlchemy models, database access layer, local SQLite file
├── aws_config/             CloudFormation templates (OIDC/IAM, scheduled Fargate, full stack variants)
├── .github/workflows/      CI and image deployment workflows
├── docker-compose.yml      Local services for API and scraper
└── Makefile                ECR/Lambda helper commands
```

## Runtime Architecture

- API: FastAPI + SQLAlchemy (`api/index.py`)
- Scraper: Requests + BeautifulSoup (`web_scraper/scraper.py`)
- Database:
  - Production path: PostgreSQL/Aurora via `POSTGRES_*` env vars
  - Local fallback: `data/sqlite.db` when Postgres vars are missing
- Deploy targets:
  - API container image for AWS Lambda (`api/dockerfiles/prod/Dockerfile`)
  - Scraper container image for ECS Fargate (`web_scraper/Dockerfile`)

## Environment Variables

Core database variables:

- `POSTGRES_HOST`
- `POSTGRES_PORT` (default `5432`)
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

Scraper behavior flags:

- `SCRAPER_ALLOW_CREATE_WATER_LOCATION` (`true/false`, default `false`)
- `SCRAPER_GEOCODE` (`true/false`, default `false`)
- `GV3_API_KEY` (required only when geocoding is enabled)

## Local Development

### Option 1: Docker Compose

From repo root:

```bash
docker compose build
docker compose up
```

Useful targets:

- API dev service only: `docker compose up api-dev`
- API prod image locally: `docker compose up api-prod`
- Scraper only: `docker compose up web-scraper`

### Option 2: Python Directly

From repo root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r web_scraper/requirements.txt
pip install -r api/requirements.txt
```

Run scraper:

```bash
python -m web_scraper.scraper
```

Run API:

```bash
uvicorn api.index:app --reload --port 8080
```

API docs: `http://localhost:8080/docs`

## API Endpoints

Main routes in `api/index.py`:

- `GET /`
- `GET /stocked_lakes_data`
- `GET /stocked_lakes_data_all_time`
- `GET /total_stocked_by_date_data`
- `GET /hatchery_totals`
- `GET /derby_lakes_data`
- `GET /date_data_updated`
- `GET /hatchery_names`

Date-filtered endpoints accept optional `start_date` and `end_date` (ISO format). Defaults are last 7 days.

## CI/CD and Deployment

- `.github/workflows/deploy-scraper.yml`
  - On push to `main`, builds and pushes both scraper and API images to ECR.
  - Uses GitHub OIDC (`AWS_ROLE_ARN`) to assume an AWS role.
- `.github/workflows/python-app.yml`
  - Lints with flake8 and runs pytest.
- `.github/workflows/deploy-to-ecr.yml`
  - Additional scraper image push workflow (also on `main`).

Infra templates:

- `aws_config/configure-aws-credentials-latest.yml`: IAM role/OIDC provider setup for GitHub Actions.
- `aws_config/scheduled-scraper-fargate.yaml`: Scheduled EventBridge -> ECS Fargate scraper task using Secrets Manager.
- `aws_config/full-api-creation.yaml` and `aws_config/fargate-rds-secrets.yaml`: broader/legacy stack templates kept in-repo.

## Notes and Constraints

- If Postgres env vars are missing, the app falls back to SQLite (`data/sqlite.db`).
- Scraper write behavior is intentionally conservative by default: if a water location does not already exist and create mode is off, the row is skipped.
- API responses use cache headers and ETags; the all-time route keeps an in-memory cache (~12 hours) to reduce query cost.

## License

MIT
