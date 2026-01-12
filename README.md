# Troutlytics Backend

Backend pipeline for Troutlytics. Scrapes Washington trout stocking data, cleans it, and stores it in PostgreSQL for use by dashboards, maps, and analysis tools. The scraper runs on a scheduled AWS Fargate task and the API is packaged for AWS Lambda or containerized hosting.

## Repository Layout

```bash
.
├── api/              FastAPI service that serves stocking data (see api/README.md)
├── web_scraper/      Scraper that pulls WDFW data and geocodes locations (see web_scraper/README.md)
├── data/             SQLAlchemy models, local SQLite database, and backups
├── aws_config/       CloudFormation templates for Fargate, RDS, and IAM
├── docker-compose.yml
└── Makefile
```

## Prerequisites

- AWS account with permissions to deploy CloudFormation, ECR, ECS/Fargate, and Secrets Manager
- AWS CLI configured locally
- Docker
- Python 3.11+ (for local runs without containers)

## Quick Start (Docker Compose)

From the repository root:

- Build all images: `docker compose build`
- Start API and scraper: `docker compose up`
- Run only the API (dev): `docker compose up api-dev`
- Run only the scraper: `docker compose up web-scraper`
- View logs: `docker compose logs -f`
- Stop and clean up: `docker compose down`

Provide environment variables via a `.env` file in the project root; Docker Compose will pass them to each service.

## Cloud Deployment

Deploy core infrastructure with CloudFormation:


```bash
aws cloudformation deploy \
  --template-file aws_config/configure-aws-credentials-latest.yml \
  --stack-name troutlytics-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ECRImageUriScraper=123456789012.dkr.ecr.us-west-2.amazonaws.com/scraper:latest \
    ECRImageUriAPI=123456789012.dkr.ecr.us-west-2.amazonaws.com/api:latest \
    VpcId=vpc-xxxxxxxx \
    SubnetIds=subnet-aaaa,subnet-bbbb \
    SecurityGroupId=sg-xxxxxxxx
```

Secrets Manager should store the database credentials used by the scraper and API. CloudWatch Logs is configured for both services.

## CI/CD

- GitHub Actions build and push container images to ECR on pushes to `main`.
- OIDC-based IAM role is required for the GitHub workflow; supply the role ARN as a repository secret.

## License

MIT
