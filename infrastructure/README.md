# FireWatch AWS Infrastructure

TypeScript CDK project for deploying FireWatch to AWS.

## ⚠️ Cost Warning

**Before deploying, read [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for important cost information.**

**Minimum cost even when idle:**
- **MSK Serverless**: ~$39/month (NAT + VPC Endpoint only)
- MSK Serverless itself: ~$0/month when idle (pay only for data)

**Design Pattern**: 
- Compute (ECS) is fully pay-as-you-go and can scale to 0
- MSK Serverless is pay-as-you-go for data, ~$0 when idle
- Infrastructure (NAT, VPC Endpoint) has minimal fixed costs

See documentation:
- [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) - Cost breakdown and optimization strategies
- [docs/MSK_SERVERLESS.md](docs/MSK_SERVERLESS.md) - MSK Serverless technical guide

## Architecture

The infrastructure deploys:

- **VPC**: Multi-AZ VPC with public, private, and isolated subnets
  - 1 NAT Gateway (default, configurable for HA)
  - VPC Endpoint for S3 (enabled by default to reduce NAT costs)
- **MSK (Kafka)**: MSK Serverless cluster
  - Pay-as-you-go, no idle costs
  - IAM authentication
  - Automatic scaling
- **ECS Fargate**: Containerized services for:
  - Fire Detection Stream (ML inference)
  - S3 Upload Consumer
  - Video Producer (on-demand)
- **S3**: Bucket for storing overlayed videos
- **ECR**: Container registries for each service
- **CloudWatch**: Logging and monitoring

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **Node.js** 18+ and npm
3. **AWS CDK CLI** installed:
   ```bash
   npm install -g aws-cdk
   ```
4. **Docker** for building container images

## Setup

1. **Install dependencies:**
   ```bash
   cd infrastructure
   npm install
   ```

2. **Bootstrap CDK** (first time only):
   ```bash
   cdk bootstrap
   ```

3. **Build the project:**
   ```bash
   npm run build
   ```

## Testing

Run unit tests to verify infrastructure components:

```bash
npm test
```

Run tests in watch mode:
```bash
npm test -- --watch
```

Run a specific test file:
```bash
npm test -- firewatch-stack.test.ts
```

Run tests with coverage:
```bash
npm test -- --coverage
```

**Test Coverage:**
- FireWatchStack: VPC, MSK, S3, ECS configuration
- MSKServerlessCluster: IAM auth, security groups, VPC integration
- S3Bucket: Encryption, versioning, lifecycle rules
- ECSCluster: Cluster, services, auto-scaling
- FireDetectionService: Task definition, container config, scaling
- S3UploadService: Task definition, container config
- VideoProducerService: Task definition, one-off task design

Tests are automatically run by `scripts/deploy.sh` before deployment.

## Deployment

### Deploy Everything

```bash
cdk deploy
```

### Deploy with Custom Configuration

**Default:**
```bash
cdk deploy  # Uses MSK Serverless
```

**Custom Settings:**
```bash
cdk deploy --context natGateways=1 --context enableS3VpcEndpoint=true
```

### View Changes Before Deploying

```bash
cdk diff
```

### Synthesize CloudFormation Templates

```bash
cdk synth
```

## Configuration

Edit `bin/firewatch-cdk.ts` to customize:

- AWS region
- NAT gateway count (default: 1)
- S3 VPC endpoint (default: enabled)
- ECS cluster name
- S3 bucket name

Or pass context variables:

```bash
cdk deploy --context natGateways=1 --context enableS3VpcEndpoint=true
```

## Building Docker Images

Before deploying, you need to build and push Docker images to ECR:

### 1. Authenticate with ECR

```bash
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com
```

### 2. Build and Push Images

Create Dockerfiles for each service, then:

```bash
# Fire Detection Stream
docker build -t firewatch/fire-detection-stream:latest -f Dockerfile.fire-detection .
docker tag firewatch/fire-detection-stream:latest <account-id>.dkr.ecr.<region>.amazonaws.com/firewatch/fire-detection-stream:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/firewatch/fire-detection-stream:latest

# S3 Upload Consumer
docker build -t firewatch/s3-upload-consumer:latest -f Dockerfile.s3-upload .
docker tag firewatch/s3-upload-consumer:latest <account-id>.dkr.ecr.<region>.amazonaws.com/firewatch/s3-upload-consumer:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/firewatch/s3-upload-consumer:latest

# Video Producer
docker build -t firewatch/video-producer:latest -f Dockerfile.producer .
docker tag firewatch/video-producer:latest <account-id>.dkr.ecr.<region>.amazonaws.com/firewatch/video-producer:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/firewatch/video-producer:latest
```

## Environment Variables

The services are configured via environment variables. Key variables:

- `KAFKA_BOOTSTRAP_SERVERS`: MSK bootstrap servers (auto-configured)
- `S3_BUCKET`: S3 bucket name (auto-configured)
- `AWS_REGION`: AWS region (auto-configured)
- `ML_MODEL_TYPE`: Model type (default: fire-detect-nn)
- `CONFIDENCE_THRESHOLD`: Detection threshold (default: 0.5)

## Scaling

Services are configured with auto-scaling:

- **Fire Detection Stream**: 1-10 tasks (CPU/Memory based)
- **S3 Upload Consumer**: 1-5 tasks (CPU based)

Adjust scaling policies in the service construct files.

## Monitoring

- **CloudWatch Logs**: All services log to `/firewatch/<service-name>`
- **ECS Container Insights**: Enabled for cluster monitoring
- **MSK Monitoring**: Enhanced monitoring enabled

## Costs

### ⚠️ Important: Minimum Costs Even When Idle

**Some services charge even when completely idle:**
- **MSK Serverless**: ~$0/month when idle (pay only for data)
- **NAT Gateway**: ~$32/month (1 gateway, charges per hour)
- **VPC Endpoint**: ~$7/month (saves money by reducing NAT usage)

**Minimum idle cost:**
- **MSK Serverless**: ~$39/month (NAT + VPC Endpoint only)

### Active Usage Costs (us-east-1, optimized):

- **MSK Serverless**: ~$5-60/month (pay per GB ingested/stored)
- ECS Fargate (2 tasks, 4GB/2CPU, Spot): ~$45-75/month (70% discount, can scale to 0)
- S3 Storage: Variable (pay per GB, $0 when no data)
- NAT Gateway (1x): ~$32/month (reduced from 2, charges when idle)
- VPC Endpoint (S3): ~$7/month (reduces NAT costs, charges when idle)
- CloudWatch: ~$5-10/month (pay per GB ingested)

**Total with usage:**
- **MSK Serverless**: ~$95-190/month (low to medium usage)

**To minimize costs:**
- ✅ MSK Serverless eliminates idle costs - pay only for data
- Scale ECS tasks to 0 when not processing (saves ~$45-75/month)
- Delete stack when not in use (saves all costs)
- See [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for detailed cost breakdown

**Cost Optimizations:**
- ✅ VPC Endpoint for S3 (eliminates NAT gateway traffic for S3)
- ✅ Fargate Spot capacity (up to 70% discount)
- ✅ Single NAT gateway (configurable, default 1)
- ✅ Auto-scaling (pay only for what you use, can scale to 0)
- ✅ S3 lifecycle policies (automatic cost reduction)

**At Scale (24/7, 1+ year):**
- Consider AWS Savings Plans (up to 66% savings on compute)
- See [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md) for:
  - Detailed cost breakdown
  - Optimization strategies
  - Scaling strategies

## Cleanup

To destroy all resources:

```bash
cdk destroy
```

**Warning**: This will delete all resources including S3 bucket (if not set to RETAIN).

## Troubleshooting

### MSK Connection Issues

- Verify security groups allow port 9098 (MSK Serverless uses port 9098)
- Check IAM permissions for MSK access
- Verify ECS task role has `kafka-cluster:Connect`, `kafka-cluster:ReadData`, `kafka-cluster:WriteData` permissions
- Check VPC routing and NAT gateway configuration
- Verify ECS tasks are in private subnets with NAT gateway access
- Verify Kafka client is configured for IAM authentication (see [MSK_SERVERLESS.md](docs/MSK_SERVERLESS.md))

### ECS Tasks Failing

- Check CloudWatch logs: `/firewatch/<service-name>`
- Verify ECR images are pushed and tagged correctly
- Check IAM roles have necessary permissions
- Verify environment variables are set correctly

### S3 Upload Failures

- Check IAM task role has S3 write permissions
- Verify KMS key permissions if encryption is enabled
- Check bucket policy and CORS configuration

## Next Steps

1. Build and push Docker images (see [DEPLOYMENT.md](DEPLOYMENT.md))
2. Deploy infrastructure: `cdk deploy`
3. Set up CI/CD pipeline for automated deployments
4. Add CloudWatch alarms and dashboards
5. Monitor costs using AWS Cost Explorer
6. Set up backup and disaster recovery

