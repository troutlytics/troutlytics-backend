# Trout Tracker WA Web Scraper

## Introduction

The Scraper folder houses the scripts responsible for scraping data from the WDFW website and transforming it for use.

### Getting Started

- Ensure the `./web_scraper` dependencies are installed.
- Set up a `.env` file with the necessary API keys.

### Features

- Automated data scraping from the WDFW website.
- Data transformation into a structured format.
- API for sending data across multiple resources
- Manual backups for extra durability
- CI/CD testing with Pytest and GitHub actions

### Running the web scraper

- copy/paste the `sample.env` contents into a new file named `.env`
- Get a [Google Geocoding API key](https://developers.google.com/maps/documentation/geolocation/overview)
- Update the environmental variable `GV3_API_KEY` with your API Key
- Then run:

        python -m web_scraper.scraper

- #### To run development server (Flask)

            python -m api.wsgi

#### Or with Docker

        docker compose -f 'docker-compose.yml' up -d --build 'web-scraper'
        docker compose run --rm web-scraper

### Data Handling

- Instructions on how the scraped data is processed and stored

#### Contributions

- [Guidelines for improving the scraper's functionality](../CONTRIBUTING.md).

#### License

- MIT License

#### Contact

- Developer: Thomas Basham
- Email: bashamtg@gmail.com
