# Troutlytics WA API

FastAPI service that exposes Washington trout stocking data for dashboards, maps, and internal tools. The service reads from the shared SQLAlchemy models in `data/` and is deployable to AWS Lambda via Mangum or as a long-running container.

## Stack & Capabilities

- FastAPI + Uvicorn with automatic OpenAPI docs (`/docs` and `/redoc`)
- Shared SQLAlchemy models (`data/models.py`) with PostgreSQL primary storage and SQLite fallback for local tinkering
- CORS enabled for read-only public consumption
- Production Lambda entrypoint provided by `Mangum` (see `handler = Mangum(app)` in `api/index.py`)

## Environment Configuration

The API expects database credentials in the environment (typically through `.env` in Docker Compose or AWS Secrets Manager):

| Variable                                        | Purpose                                |
| :---------------------------------------------- | :------------------------------------- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`            | Credentials for Aurora/PostgreSQL      |
| `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT` | Connection target (defaults to `5432`) |

If any of the values above are missing, the service automatically falls back to the local SQLite file at `data/sqlite.db`. This is useful for quick demos but will only include whatever data has been imported into that file.

## Local Development

### Python tooling

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r api/requirements.txt
   ```
2. Export or copy your database environment variables.
3. Run the server (from the repository root so relative imports resolve):
   ```bash
   uvicorn api.index:app --reload --port 8080
   ```
4. Visit `http://localhost:8080/docs` for the interactive Swagger UI.

### Docker Compose

Use the repo-wide compose file to run the API just like production:

```bash
docker compose up api-dev
```

This builds `api/dockerfiles/dev/Dockerfile`, mounts environment variables from `.env`, and binds the API to `localhost:8080`.

## Deployment Notes

- `api/dockerfiles/prod/Dockerfile` plus `lambda_entry_script.sh` produce the Lambda-compatible container image used by AWS ECS/Lambda.
- `handler = Mangum(app)` allows API Gateway → Lambda integrations without modifying FastAPI routes.
- Logs are emitted with Python’s standard logging (configured at INFO).

## REST Endpoints

Unless noted, all endpoints accept optional ISO 8601 `start_date` and `end_date` query parameters. When omitted, the API defaults to the trailing 7-day window ending “now”.

### GET `/`

Returns service metadata, documented routes, and suggested usage patterns. Helpful for quick smoke-tests.

### GET `/stocked_lakes_data`

Pulls individual stocking reports joined with their water locations.

| Query param  | Type          | Description                                       |
| :----------- | :------------ | :------------------------------------------------ |
| `start_date` | ISO date/time | Beginning of the window (defaults to 7 days ago). |
| `end_date`   | ISO date/time | End of the window (defaults to now).              |

Example response:

```json
[
  {
    "date": "2024-03-18T00:00:00",
    "water_name_cleaned": "Battle Ground Lake",
    "stocked_fish": 1500,
    "species": "Rainbow",
    "hatchery": "Skamania",
    "weight": 2.5,
    "derby_participant": true,
    "water_location_id": 42,
    "latitude": 45.779,
    "longitude": -122.539,
    "directions": "From I-5 take..."
  }
]
```

### GET `/total_stocked_by_date_data`

Aggregates `stocked_fish` counts by stocking date for the requested window. Response shape:

```json
[
  { "date": "2024-03-15", "stocked_fish": 4300 },
  { "date": "2024-03-16", "stocked_fish": 2200 }
]
```

### GET `/hatchery_totals`

Aggregates total fish released per hatchery. Output is ordered descending by stocked fish:

```json
[
  { "hatchery": "Goldendale", "sum_1": 5200 },****
  { "hatchery": "Skamania", "sum_1": 4100 }
]
```

### GET `/derby_lakes_data`

Returns every record from the `derby_participant` table. Each item includes the derby `id` and `lake` name, enabling UIs to highlight contest-eligible lakes.

### GET `/date_data_updated`

Returns the most recent timestamp from the `utility.updated` column, indicating when the ETL pipeline last wrote data (stringified ISO date).

### GET `/hatchery_names`

Returns a sorted list of distinct hatchery names present in `stocking_report`. Example:

```json
["Eastbank", "Goldendale", "Skamania"]
```

### Error Handling

- When a database call raises an exception, endpoints respond with `{ "error": "<message>" }` and HTTP 200 so downstream consumers can surface the issue without failing their own polling loops.
- Invalid `start_date`/`end_date` values are coerced to their defaults rather than causing an error.

## Contact

- Developer: Thomas Basham
- Email: bashamtg@gmail.com
