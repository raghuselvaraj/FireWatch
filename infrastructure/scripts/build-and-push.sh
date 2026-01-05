#!/bin/bash
# Script to build and push Docker images to ECR

set -e

# Get AWS account ID and region
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=${AWS_REGION:-us-east-1}

# ECR repositories
REPOS=(
  "firewatch/fire-detection-stream"
  "firewatch/s3-upload-consumer"
  "firewatch/video-producer"
)

# Dockerfiles
DOCKERFILES=(
  "Dockerfile.fire-detection"
  "Dockerfile.s3-upload"
  "Dockerfile.producer"
)

# Authenticate with ECR
echo "Authenticating with ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Build and push each image
for i in "${!REPOS[@]}"; do
  REPO=${REPOS[$i]}
  DOCKERFILE=${DOCKERFILES[$i]}
  ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO"
  
  echo ""
  echo "Building $REPO..."
  docker build -t $REPO:latest -f $DOCKERFILE ..
  
  echo "Tagging $REPO..."
  docker tag $REPO:latest $ECR_URI:latest
  
  echo "Pushing $REPO to ECR..."
  docker push $ECR_URI:latest
  
  echo "✓ $REPO pushed successfully"
done

echo ""
echo "All images pushed successfully!"

