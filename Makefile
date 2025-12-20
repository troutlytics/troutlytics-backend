AWS_ACCOUNT_ID ?= 489702352871
REGION ?= us-west-2
REPO_NAME ?= troutlytics-api
REGISTRY := $(AWS_ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com
IMAGE_LOCAL ?= api-prod:latest
IMAGE_REMOTE := $(REGISTRY)/$(REPO_NAME):latest
DOCKER_COMPOSE ?= docker compose

.PHONY: build login ensure-repo tag push publish

# Build the API image defined in docker-compose.yml (api-prod service).
build:
	$(DOCKER_COMPOSE) build api-prod

# Authenticate Docker to ECR.
login:
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(REGISTRY)

# Create the ECR repo if it does not already exist.
ensure-repo:
	aws ecr describe-repositories --repository-names $(REPO_NAME) --region $(REGION) >/dev/null 2>&1 || \
	aws ecr create-repository --repository-name $(REPO_NAME) --region $(REGION)

# Tag the built image for ECR.
tag: build
	docker tag $(IMAGE_LOCAL) $(IMAGE_REMOTE)

updateLambda:
	aws lambda update-function-code \
           --function-name troutlytics-api \
           --image-uri 489702352871.dkr.ecr.us-west-2.amazonaws.com/troutlytics-api:latest

# Push the image to ECR.
push: login ensure-repo tag
	docker push $(IMAGE_REMOTE) 

# Full pipeline: build, tag, and push.
publish: push

