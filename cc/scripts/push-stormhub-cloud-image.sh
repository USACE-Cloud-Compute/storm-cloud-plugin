#!/bin/bash

set -e

# User: Fill in these variables
LOCAL_IMAGE_NAME="cc-stormhub-cloud"
LOCAL_IMAGE_TAG="latest"

AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="123456789012"
ECR_REPOSITORY="stormhub-cloud"
ECR_IMAGE_TAG="latest"

ECR_URL="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${ECR_IMAGE_TAG}"

# Authenticate Docker to AWS ECR
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Tag the image
docker tag "${LOCAL_IMAGE_NAME}:${LOCAL_IMAGE_TAG}" "$ECR_URL"

# Push the image
docker push "$ECR_URL"