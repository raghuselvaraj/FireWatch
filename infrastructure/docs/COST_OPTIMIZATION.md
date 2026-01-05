# FireWatch Cost Optimization Guide

This document outlines cost optimization strategies, pay-as-you-go services, and MSK configuration trade-offs.

## ⚠️ Critical: Services That Charge Even When Idle

**Before deploying, understand these costs will occur even with zero usage:**

| Service | Monthly Cost (Idle) | Can Scale to 0? | Notes |
|---------|-------------------|-----------------|-------|
| **MSK Serverless** | ~$0/month | ✅ Yes | Pay only for data ingested/stored |
| **NAT Gateway** | ~$32/month (1 gateway) | ⚠️ Partial | Can reduce to 0 with VPC endpoints |
| **VPC Endpoint (S3)** | ~$7/month | ⚠️ Partial | Saves money by reducing NAT usage |

**Total Minimum Cost (Idle):**
- **MSK Serverless**: ~$39/month (NAT + VPC Endpoint only)

**To minimize idle costs:**
- ✅ MSK Serverless eliminates ~$450/month idle cost (vs provisioned MSK)
- ✅ Use VPC endpoints for all AWS services (S3, DynamoDB, etc.)
- ✅ Scale ECS tasks to 0 when not processing (saves ~$45-75/month)
- ✅ Delete stack when not in use (saves all costs)

## MSK Serverless Overview

**Note**: This CDK stack uses MSK Serverless exclusively. The following section provides context on why Serverless was chosen over Provisioned MSK.

### Quick Comparison

| Factor | MSK Serverless | MSK Provisioned |
|--------|----------------|-----------------|
| **Idle Cost** | ~$0/month | ~$450/month (3 brokers) |
| **Active Cost** | ~$0.10/GB ingested + $0.10/GB/month stored | ~$450/month (fixed) |
| **Max Throughput** | 200 MB/s per cluster | Unlimited (scales with brokers) |
| **Max Partitions** | 2,000 per cluster | Unlimited |
| **Authentication** | IAM only | TLS, SASL, IAM |
| **Configuration Control** | Limited | Full control |
| **Scaling** | Automatic | Manual (add/remove brokers) |
| **Best For** | Variable workloads, cost-conscious | High throughput, predictable workloads |

### Detailed Trade-Offs

#### 💰 Cost Analysis

**MSK Serverless (Pay-as-You-Go)**
- **Idle**: ~$0/month (no data = no cost)
- **Low usage** (10GB ingested, 50GB stored): ~$5-10/month
- **Medium usage** (100GB ingested, 500GB stored): ~$60/month
- **High usage** (1TB ingested, 2TB stored): ~$210/month

**MSK Provisioned (Fixed Cost)**
- **Idle**: ~$450/month (3 brokers, m5.large)
- **Any usage**: ~$450/month (cost doesn't change with data volume)
- **With Reserved Capacity** (1-year): ~$315/month (30% savings)

**Break-Even Point**: 
- MSK Serverless is cheaper until you process **~4.5TB/month**
- At very high throughput (>200 MB/s), Provisioned may be required
- For 24/7 high-volume workloads, Reserved Capacity can make Provisioned cheaper

#### ⚡ Performance & Scalability

**MSK Serverless**
- ✅ Automatic scaling (no manual intervention)
- ✅ No capacity planning needed
- ⚠️ Max 200 MB/s per cluster (may be limiting for very high throughput)
- ⚠️ Max 2,000 partitions per cluster
- ✅ Instant scaling up/down

**MSK Provisioned**
- ✅ Unlimited throughput (scales with broker count and instance size)
- ✅ Unlimited partitions
- ⚠️ Manual scaling (add/remove brokers, may take 10-20 minutes)
- ⚠️ Requires capacity planning
- ✅ Predictable performance

#### 🔧 Configuration & Control

**MSK Serverless**
- ⚠️ Limited configuration options (AWS manages everything)
- ✅ No broker management
- ✅ Automatic updates and patching
- ⚠️ Cannot customize broker settings

**MSK Provisioned**
- ✅ Full control over broker configuration
- ✅ Custom Kafka configurations
- ✅ Choose instance types and storage
- ⚠️ Manual updates and patching
- ⚠️ More operational overhead

#### 🔐 Security & Authentication

**MSK Serverless**
- ✅ IAM authentication (integrated with AWS)
- ⚠️ IAM only (no TLS/SASL options)
- ✅ Automatic encryption in transit
- ✅ Automatic encryption at rest

**MSK Provisioned**
- ✅ IAM, TLS, SASL/SCRAM authentication options
- ✅ More authentication flexibility
- ✅ Custom encryption keys (KMS)
- ✅ Network-level security controls

#### 📊 When to Use Each

**✅ Use MSK Serverless When:**
- Variable or unpredictable workloads
- Cost-conscious deployments (want to minimize idle costs)
- Development/testing environments
- Low to medium throughput (< 200 MB/s)
- Want automatic scaling
- Don't need fine-grained broker control
- **Default choice for most use cases**

**✅ Use MSK Provisioned When:**
- High throughput requirements (> 200 MB/s)
- Predictable, consistent 24/7 workloads
- Need more than 2,000 partitions
- Need fine-grained control over broker configuration
- Need TLS/SASL authentication (not just IAM)
- Running 24/7 with high utilization (may be cheaper with Reserved Capacity)
- **Specialized high-performance use cases**

### Cost Scenarios

#### Scenario 1: Development/Testing (Variable Usage)
- **Usage**: 0-50GB/month, sporadic
- **MSK Serverless**: ~$0-5/month
- **MSK Provisioned**: ~$450/month
- **Winner**: MSK Serverless (saves ~$445-450/month)

#### Scenario 2: Production (Low-Medium Usage)
- **Usage**: 100GB ingested, 500GB stored/month
- **MSK Serverless**: ~$60/month
- **MSK Provisioned**: ~$450/month
- **Winner**: MSK Serverless (saves ~$390/month)

#### Scenario 3: Production (High Usage)
- **Usage**: 1TB ingested, 2TB stored/month
- **MSK Serverless**: ~$210/month
- **MSK Provisioned**: ~$450/month
- **Winner**: MSK Serverless (saves ~$240/month)

#### Scenario 4: Production (Very High Usage, 24/7)
- **Usage**: 5TB+ ingested/month, 24/7 operation
- **MSK Serverless**: ~$500+/month (may hit throughput limits)
- **MSK Provisioned**: ~$450/month (or ~$315/month with Reserved Capacity)
- **Winner**: MSK Provisioned (better performance + cost at scale)

### Why This Stack Uses MSK Serverless

This CDK stack uses MSK Serverless exclusively because:
- **Eliminates idle costs**: ~$450/month savings when not processing
- **Automatic scaling**: Matches variable video processing workloads
- **Sufficient throughput**: 200 MB/s is adequate for most video processing scenarios
- **Simplified operations**: No broker management or capacity planning needed
- **IAM integration**: Seamless authentication with ECS task roles

**Note**: If you need provisioned MSK (for throughput > 200 MB/s or > 2,000 partitions), you would need to modify the CDK stack or use a separate provisioned MSK cluster.

## Pay-as-You-Go Services

All services in FireWatch are configured to use pay-as-you-go pricing:

### ✅ Already Pay-as-You-Go

1. **ECS Fargate** - Pay only for running tasks
   - Charges per vCPU-hour and GB-hour
   - No upfront costs or minimum commitments
   - Can scale to 0 = $0 when idle
   - Auto-scales based on demand

2. **S3** - Pay only for storage and requests
   - Storage: $0.023/GB/month (Standard)
   - Requests: $0.0004 per 1,000 PUT requests
   - No minimum fees, $0 when empty

3. **CloudWatch** - Pay only for logs and metrics
   - Logs: $0.50/GB ingested
   - Metrics: $0.30/metric/month (first 10,000 free)
   - No minimum fees, $0 when no logs

4. **ECR** - Pay only for storage
   - Storage: $0.10/GB/month
   - No charges for image pulls
   - $0 when no images

5. **KMS** - Pay only for API calls
   - $0.03 per 10,000 requests
   - First 20,000 requests/month free

6. **MSK Serverless** - Pay only for data
   - ~$0.10/GB ingested
   - ~$0.10/GB/month stored
   - $0 when idle (no data)

### 💰 Cost Optimizations Implemented

#### 1. MSK Serverless (Default)
- **Savings**: Eliminates ~$450/month idle cost
- **Impact**: Reduces minimum cost from ~$489/month to ~$39/month
- **Trade-off**: Limited to 200 MB/s throughput

#### 2. VPC Endpoint for S3
- **Cost**: ~$7/month per endpoint
- **Savings**: Eliminates NAT gateway data transfer costs for S3
- **Impact**: Reduces NAT gateway usage by ~80-90% for S3 traffic

#### 3. Reduced NAT Gateways
- **Default**: 1 NAT gateway (instead of 2)
- **Cost**: ~$32/month (vs ~$65/month for 2)
- **Trade-off**: Less redundancy, but VPC endpoint handles S3 traffic
- **Configurable**: Can increase to 2+ for high availability

#### 4. Fargate Spot Capacity
- **Savings**: Up to 70% discount on compute costs
- **Implementation**: Prefers Spot, falls back to regular Fargate
- **Impact**: Can reduce ECS costs from ~$150/month to ~$45-75/month

#### 5. Auto-Scaling
- **ECS Services**: Scale from 1-10 tasks based on demand
- **Impact**: Pay only for what you use
- **Idle**: Can scale to 0 tasks when not processing

#### 6. S3 Lifecycle Policies
- **Standard → IA**: After 30 days (50% cost reduction)
- **IA → Glacier**: After 90 days (68% cost reduction)
- **Impact**: Reduces storage costs for older videos

## Cost Breakdown

### Monthly Costs (us-east-1, optimized configuration with MSK Serverless)

| Component | Cost | Notes |
|-----------|------|-------|
| MSK Serverless | ~$0-60 | Pay per GB (varies with usage) |
| ECS Fargate (2 tasks avg, Spot) | ~$45-75 | 70% discount with Spot, can scale to 0 |
| S3 Storage (100GB) | ~$2.30 | Pay per GB |
| S3 Requests | ~$1 | Pay per request |
| NAT Gateway (1x) | ~$32 | Reduced from 2 |
| VPC Endpoint (S3) | ~$7 | Reduces NAT gateway costs |
| CloudWatch Logs | ~$5-10 | Pay per GB |
| **Total (Active)** | **~$90-190/month** | vs ~$540-580/month with Provisioned MSK |
| **Total (Idle)** | **~$39/month** | vs ~$489/month with Provisioned MSK |

### Cost Savings

- **MSK Serverless**: ~$450/month savings when idle
- **NAT Gateway**: ~$33/month (1 vs 2)
- **Fargate Spot**: ~$75-105/month (70% discount)
- **VPC Endpoint**: Saves ~$10-20/month in NAT gateway data transfer
- **Total Savings**: ~$568-608/month vs unoptimized Provisioned MSK setup

## Configuration Options

### Default Configuration (Recommended)

```typescript
new FireWatchStack(app, 'FireWatchStack', {
  natGateways: 1,                // Cost savings (default)
  enableS3VpcEndpoint: true,      // Cost savings (default)
  // MSK Serverless is automatically used
});
```

**Cost**: ~$39/month idle, ~$90-190/month active

### High Availability Configuration

```typescript
new FireWatchStack(app, 'FireWatchStack', {
  natGateways: 2,                // HA across AZs
  enableS3VpcEndpoint: true,
  // MSK Serverless is automatically used
});
```

**Cost**: ~$71/month idle, ~$120-220/month active

## Cost Optimization at Scale

When running at scale (24/7, predictable workloads), consider provisioned resources for additional savings:

### AWS Savings Plans

**When to Use:** Running 24/7 with predictable compute usage

**Options:**
1. **Compute Savings Plans** - Up to 66% savings
   - Applies to: ECS Fargate, Lambda, EC2
   - Commitment: 1-3 years
   - **Best for**: Consistent ECS Fargate usage
   - **Savings**: ~$30-50/month if using $150/month in Fargate

2. **EC2 Instance Savings Plans** - Up to 72% savings
   - Applies to: Specific EC2 instance families
   - **Not applicable**: We use Fargate, not EC2

**Recommendation:** Only consider if running 24/7 with consistent usage. For variable workloads, pay-as-you-go is better.

### MSK Serverless Cost Optimization

**MSK Serverless automatically optimizes costs:**
- **No idle costs**: Pay only when processing data
- **Automatic scaling**: No over-provisioning
- **Data retention**: Configure retention policies to minimize storage costs
- **Compression**: Use message compression to reduce data volume

**Recommendation:** MSK Serverless is already optimized for cost. Focus on:
- Setting appropriate retention periods
- Using message compression
- Monitoring data ingestion/storage metrics

### S3 Storage Classes

**For High Volume Storage:**

1. **S3 Intelligent-Tiering**
   - Automatically moves objects between access tiers
   - No retrieval fees
   - **Best for**: Unknown access patterns
   - **Savings**: 40-68% vs Standard storage

2. **S3 Glacier Instant Retrieval**
   - For rarely accessed data
   - **Cost**: $0.004/GB/month (vs $0.023/GB for Standard)
   - **Savings**: 83% reduction
   - **Best for**: Video archives accessed <1x/month

3. **S3 Glacier Flexible Retrieval**
   - For archival data
   - **Cost**: $0.0036/GB/month
   - **Savings**: 84% reduction
   - **Best for**: Long-term archives

### Cost Optimization Strategy by Scale

| Scale | Strategy | Monthly Cost | Notes |
|-------|----------|--------------|-------|
| **Development/Testing** | MSK Serverless, scale to 0 | ~$39 (idle) | Minimum fixed costs |
| **Low Volume** | MSK Serverless, auto-scaling | ~$90-190 | Current optimized setup |
| **Medium Volume (24/7)** | MSK Serverless + S3 Intelligent-Tiering | ~$100-200 | Add S3 optimization |
| **High Volume (24/7, 1+ year)** | MSK Provisioned + Reserved Capacity | ~$400-500 | Requires commitment |
| **Very High Volume** | MSK Provisioned + Reserved + S3 Glacier | ~$350-450 | Maximum savings |

### When to Use Provisioned Resources

**✅ Use Reserved Capacity/Savings Plans When:**
- Running 24/7 for 1+ years
- Predictable, consistent workload
- Cost savings justify commitment
- Budget allows for upfront planning

**❌ Don't Use Reserved Capacity When:**
- Variable or unpredictable workloads
- Short-term projects (<1 year)
- Testing or development
- Uncertain about future usage

**Note**: MSK Serverless is already optimized for cost and doesn't require reserved capacity.

### Cost Optimization Checklist

**Immediate (No Commitment):**
- [x] MSK Serverless (default) - eliminates idle costs
- [x] VPC Endpoint for S3 (reduces NAT costs)
- [x] Fargate Spot (70% discount)
- [x] Single NAT Gateway (vs 2)
- [x] Auto-scaling (scale to 0 when idle)
- [x] S3 Lifecycle Policies (automatic tiering)
- [ ] S3 Intelligent-Tiering (for unknown patterns)

**At Scale (With Commitment):**
- [ ] Compute Savings Plans (if 24/7 for 1+ year)
- [ ] S3 Glacier for archives (if rarely accessed)

**Note**: MSK Serverless doesn't require reserved capacity - it's already pay-as-you-go.

## Monitoring Costs

### CloudWatch Cost Alarms

Set up billing alarms to monitor costs:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name firewatch-monthly-cost \
  --alarm-description "Alert when monthly cost exceeds $200" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 200 \
  --comparison-operator GreaterThanThreshold
```

### Cost Explorer

1. Go to AWS Cost Explorer
2. Filter by service (ECS, MSK, S3, etc.)
3. Set up cost anomaly detection
4. Review monthly trends

## Best Practices

1. **Use MSK Serverless**: Default choice, eliminates idle costs
2. **Use Spot Instances**: Fargate Spot provides 70% savings
3. **VPC Endpoints**: Use for S3, DynamoDB, etc. to reduce NAT costs
4. **Auto-Scaling**: Scale down during low usage periods
5. **Lifecycle Policies**: Move old data to cheaper storage tiers
6. **Right-Sizing**: Monitor and adjust resource sizes
7. **Tag Resources**: Use tags for cost allocation and tracking

## Cost Comparison Summary

### MSK Serverless vs Provisioned

| Configuration | Idle Cost | Active Cost (Low) | Active Cost (High) |
|--------------|-----------|-------------------|-------------------|
| MSK Serverless (default) | ~$39/month | ~$90-190/month | ~$200-300/month |
| MSK Provisioned | ~$489/month | ~$540-580/month | ~$540-580/month |
| **Savings with Serverless** | **~$450/month** | **~$350-390/month** | **~$240-280/month** |

### Development vs Production

| Environment | Monthly Cost (Idle) | Monthly Cost (Active) |
|------------|---------------------|----------------------|
| Development (MSK Serverless) | ~$39 | ~$90-190 |
| Production (MSK Serverless) | ~$39 | ~$100-200 |

## Questions?

For cost optimization questions:
- Review AWS Cost Explorer
- Check CloudWatch metrics for resource utilization
- **Before committing**: Use pay-as-you-go for 1-3 months to understand usage patterns
- Use AWS Cost Anomaly Detection for unexpected charges
- Consider AWS Cost Explorer's "Reserved Instance Recommendations"

**Recommendation**: This CDK stack uses MSK Serverless exclusively, which is optimal for most use cases. MSK Serverless eliminates idle costs and automatically scales to match your workload. If you need throughput > 200 MB/s or > 2,000 partitions, you would need to use a separate provisioned MSK cluster (not included in this stack).
