# FireWatch AWS Deployment Guide

## ⚠️ Cost Warning

**Before deploying, read [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for important cost information.**

**Minimum cost even when idle:**
- **MSK Serverless**: ~$39/month (NAT + VPC Endpoint only)
- MSK Serverless itself: ~$0/month when idle (pay only for data)

**To minimize costs:**
- ✅ MSK Serverless eliminates ~$450/month idle cost (vs provisioned MSK)
- Scale ECS tasks to 0 when not processing
- Delete stack when not in use
- See [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for detailed cost breakdown

## Quick Start

1. **Install dependencies:**
   ```bash
   cd infrastructure
   npm install
   ```

2. **Bootstrap CDK** (first time only):
   ```bash
   cdk bootstrap
   ```

3. **Build and push Docker images:**
   ```bash
   ./scripts/build-and-push.sh
   ```

4. **Deploy infrastructure:**
   ```bash
   cdk deploy
   ```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    AWS VPC (Multi-AZ)                   │
│                                                         │
│  ┌──────────────┐       ┌──────────────┐                │
│  │  MSK Cluster │       │  ECS Cluster │                │
│  │  (Kafka)     │◄──────┤  (Fargate)   │                │
│  │  Serverless  │       │              │                │
│  └──────────────┘       └──────┬───────┘                │
│                                │                        │
│                    ┌───────────┴───────────┐            │
│                    │                       │            │
│          ┌─────────▼─────────┐   ┌─────────▼─────────┐  │
│          │ Fire Detection    │   │ S3 Upload         │  │
│          │ Stream Service    │   │ Consumer Service  │  │
│          │ (2-10 tasks)      │   │ (1-5 tasks)       │  │
│          └───────────────────┘   └───────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  S3 Bucket   │
                    │  (Videos)    │
                    └──────────────┘
```

## Components

### 1. VPC
- 3 Availability Zones
- Public subnets (NAT gateway - 1 by default for cost savings)
- Private subnets (ECS tasks)
- Isolated subnets (MSK Serverless cluster)
- VPC Endpoint for S3 (enabled by default to reduce NAT costs)

### 2. MSK (Kafka)
- **MSK Serverless**: Pay-as-you-go, no idle costs
  - IAM authentication
  - Automatic scaling
  - Max 200 MB/s throughput
  - Max 2,000 partitions per cluster
- Auto-created topics enabled
- 6 partitions per topic (for scaling)

### 3. ECS Services
- **Fire Detection Stream**: ML inference + video overlay
- **S3 Upload Consumer**: Uploads videos to S3
- **Video Producer**: On-demand video processing

### 4. S3 Bucket
- Encrypted (KMS)
- Versioned
- Lifecycle policies (IA → Glacier)
- CORS enabled

## Configuration

### Environment Variables

Set in CDK context or edit `bin/firewatch-cdk.ts`:

**Configuration:**
```typescript
new FireWatchStack(app, 'FireWatchStack', {
  env: {
    account: '123456789012',
    region: 'us-east-1',
  },
  natGateways: 1,           // Default: 1 for cost savings
  enableS3VpcEndpoint: true, // Default: true (reduces NAT costs)
  s3BucketName: 'firewatch-videos-prod',
});
```

**Via CDK Context:**
```bash
cdk deploy --context natGateways=1 --context enableS3VpcEndpoint=true
```

### Service Configuration

Services are configured via environment variables in the task definitions. Key settings:

- **Fire Detection Stream**: 4GB RAM, 2 CPU, scales 1-10 tasks
- **S3 Upload Consumer**: 2GB RAM, 1 CPU, scales 1-5 tasks
- **Video Producer**: 1GB RAM, 0.5 CPU (on-demand)

## Deployment Steps

### 1. Prerequisites

```bash
# Install AWS CDK
npm install -g aws-cdk

# Configure AWS credentials
aws configure

# Verify CDK version
cdk --version
```

### 2. Build Docker Images

The Dockerfiles are in the infrastructure directory but reference parent directory files. Build from project root:

```bash
# From project root
cd infrastructure
./scripts/build-and-push.sh
```

Or manually:

```bash
# Get ECR login
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build and push each service
docker build -t firewatch/fire-detection-stream:latest -f infrastructure/Dockerfile.fire-detection .
docker tag firewatch/fire-detection-stream:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/firewatch/fire-detection-stream:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/firewatch/fire-detection-stream:latest
```

### 3. Deploy Infrastructure

```bash
cd infrastructure
npm install
npm run build
cdk deploy
```

### 4. Verify Deployment

```bash
# Check ECS services
aws ecs list-services --cluster firewatch-cluster

# Check MSK cluster
aws kafka list-clusters

# Check S3 bucket
aws s3 ls | grep firewatch
```

## Post-Deployment

### 1. Create Kafka Topics

MSK Serverless automatically creates topics when first used. Topics are created automatically when your producers/consumers first access them.

**Note**: MSK Serverless uses IAM authentication. Configure your Kafka client accordingly. See [infrastructure/docs/MSK_SERVERLESS.md](infrastructure/docs/MSK_SERVERLESS.md) for authentication details.

### 2. Update ECS Task Environment Variables

If you need to change configuration, update the service definitions and redeploy:

```bash
cdk deploy
```

### 3. Monitor Services

```bash
# View logs
aws logs tail /firewatch/fire-detection-stream --follow

# Check service status
aws ecs describe-services \
  --cluster firewatch-cluster \
  --services firewatch-fire-detection-service
```

## Scaling

### Manual Scaling

```bash
# Update desired count
aws ecs update-service \
  --cluster firewatch-cluster \
  --service firewatch-fire-detection-service \
  --desired-count 5
```

### Auto Scaling

Auto-scaling is configured based on:
- CPU utilization (70% target)
- Memory utilization (80% target)

Adjust in `lib/services/*-service.ts` files.

## Cost Optimization

The infrastructure is optimized for pay-as-you-go services:

1. **MSK Serverless** - Eliminates ~$450/month idle cost (vs provisioned MSK)
2. **VPC Endpoint for S3** - Enabled by default, reduces NAT gateway costs
3. **Fargate Spot** - Up to 70% discount on compute (enabled by default)
4. **Single NAT Gateway** - Default to 1 (configurable for HA)
5. **S3 Lifecycle Policies** - Automatically move old videos to cheaper tiers
6. **Auto-Scaling** - Pay only for what you use, can scale to 0

See [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for:
- Detailed cost breakdown
- Optimization strategies
- Scaling strategies

## Troubleshooting

### Services Not Starting

1. Check CloudWatch logs
2. Verify ECR images are pushed
3. Check IAM role permissions
4. Verify security group rules

### MSK Connection Issues

1. Verify security groups allow port 9098 (MSK Serverless uses port 9098)
2. Check IAM permissions for MSK access
3. Verify ECS task role has `kafka-cluster:Connect`, `kafka-cluster:ReadData`, `kafka-cluster:WriteData` permissions
4. Check VPC routing
5. Ensure ECS tasks are in private subnets with NAT gateway or VPC endpoint
6. Verify Kafka client is configured for IAM authentication (see [MSK_SERVERLESS.md](docs/MSK_SERVERLESS.md))

### High Costs

1. Review CloudWatch metrics
2. Check S3 storage usage
3. Monitor ECS task counts
4. Check MSK Serverless data ingestion/storage metrics (BytesInPerSec, BytesStored)
5. Review MSK Serverless costs in AWS Cost Explorer
6. Scale ECS tasks to 0 when not processing
7. See [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for optimization strategies

## Cleanup

```bash
# Destroy all resources
cdk destroy

# Note: S3 bucket will be retained (RETAIN policy)
# Manually delete if needed:
aws s3 rb s3://<bucket-name> --force
```

