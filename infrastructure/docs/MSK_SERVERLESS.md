# MSK Serverless Technical Guide

This guide covers technical implementation details for MSK Serverless. For cost comparisons and trade-offs, see [COST_OPTIMIZATION.md](COST_OPTIMIZATION.md).

## Overview

MSK Serverless is a pay-as-you-go Kafka service that eliminates idle costs. Instead of paying for broker-hours, you pay only for:
- **Data ingested**: ~$0.10/GB
- **Data stored**: ~$0.10/GB/month (for retention)

**Cost when idle: ~$0** (vs ~$450/month for provisioned MSK)

**Note**: MSK Serverless is the only MSK option available in this CDK stack. It eliminates idle costs compared to provisioned MSK.

## Configuration

MSK Serverless is automatically configured in the CDK stack. No additional configuration is needed:

```typescript
new FireWatchStack(app, 'FireWatchStack', {
  // MSK Serverless is automatically used
  // ... other config
});
```

## Authentication

MSK Serverless uses **IAM authentication** instead of TLS/SASL:

### For ECS Tasks

The ECS task role needs IAM permissions to access MSK Serverless:

```typescript
// IAM policy for MSK Serverless access
{
  "Effect": "Allow",
  "Action": [
    "kafka-cluster:Connect",
    "kafka-cluster:DescribeCluster",
    "kafka-cluster:ReadData",
    "kafka-cluster:WriteData"
  ],
  "Resource": "arn:aws:kafka:*:*:cluster/*/*"
}
```

### Client Configuration

Update your Kafka client to use IAM authentication:

```python
from kafka import KafkaConsumer, KafkaProducer
import boto3

# Get AWS credentials
session = boto3.Session()
credentials = session.get_credentials()

# Configure for IAM auth
consumer = KafkaConsumer(
    'video-frames',
    bootstrap_servers=msk_bootstrap_servers,
    security_protocol='SASL_SSL',
    sasl_mechanism='AWS_MSK_IAM',
    sasl_plain_username=credentials.access_key,
    sasl_plain_password=credentials.secret_key,
    # ... other config
)
```

## Migration from Provisioned MSK (External)

If you're migrating from a provisioned MSK cluster outside this CDK stack:

1. **Update Kafka client code** to use IAM authentication (see Authentication section above)

2. **Update IAM roles** to include MSK permissions

3. **Deploy the CDK stack**:
   ```bash
   cdk deploy
   ```

4. **Migrate data** (if needed):
   - Use Kafka MirrorMaker or similar tool
   - Or reprocess from source

## Limitations

- **Throughput**: Max 200 MB/s per cluster (vs unlimited for provisioned)
- **Partitions**: Max 2,000 partitions per cluster
- **Retention**: Configurable, but affects storage costs
- **Authentication**: IAM only (no TLS/SASL)

## Cost Optimization Tips

1. **Set appropriate retention**: Shorter retention = lower storage costs
2. **Monitor data ingestion**: Use CloudWatch metrics
3. **Use compression**: Reduces data volume and costs
4. **Batch messages**: Reduces per-message overhead

## Monitoring

MSK Serverless provides CloudWatch metrics:
- `BytesInPerSec`: Data ingestion rate
- `BytesOutPerSec`: Data consumption rate
- `BytesStored`: Data retention size

Set up alarms to monitor costs:
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name msk-serverless-cost \
  --metric-name BytesInPerSec \
  --namespace AWS/Kafka \
  --statistic Sum \
  --period 3600 \
  --evaluation-periods 1 \
  --threshold 1000000000 \
  --comparison-operator GreaterThanThreshold
```

## Summary

**MSK Serverless eliminates idle costs** - perfect for variable workloads and cost-conscious deployments. The default configuration uses MSK Serverless to minimize costs when idle.

