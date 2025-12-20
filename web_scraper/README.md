# Troutlytics WA Web Scraper

Scrapes trout stocking data from the WDFW site, geocodes locations, and prepares records for the API/database.

## Requirements

- Python 3.11+
- Google Geocoding API key (for `GV3_API_KEY`)
- `.env` file with required variables (see `sample.env`)
- Docker (optional, for Compose)

## Setup

1. Copy `sample.env` to `.env` and fill in values.
2. Install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r web_scraper/requirements.txt
   ```

## Run the Scraper

From the repository root:

```bash
python -m web_scraper.scraper
```

With Docker Compose:

```bash
docker compose up web-scraper
```

Both options read configuration from `.env`.

## Testing

```bash
cd web_scraper
pytest
```

## Notes

- Output data is written to the shared database defined by your environment variables.
- GitHub Actions run tests on pushes; keep tests updated with scraper changes.

## Contact

- Developer: Thomas Basham
- Email: bashamtg@gmail.com
