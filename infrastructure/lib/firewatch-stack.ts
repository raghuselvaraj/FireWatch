import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';
import { MSKServerlessCluster } from './msk-serverless-cluster';
import { ECSCluster } from './ecs-cluster';
import { S3Bucket } from './s3-bucket';

export interface FireWatchStackProps extends cdk.StackProps {
  /**
   * ECS cluster name
   * @default firewatch-cluster
   */
  clusterName?: string;

  /**
   * S3 bucket name for video storage
   * If not provided, will be auto-generated
   */
  s3BucketName?: string;

  /**
   * Enable encryption for S3 bucket
   * @default true
   */
  enableS3Encryption?: boolean;

  /**
   * Number of NAT Gateways (1 for cost savings, 2+ for high availability)
   * Using VPC endpoints for S3 reduces NAT gateway traffic
   * @default 1
   */
  natGateways?: number;

  /**
   * Enable VPC endpoint for S3 to reduce NAT gateway costs
   * @default true
   */
  enableS3VpcEndpoint?: boolean;
}

export class FireWatchStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly mskCluster: MSKServerlessCluster;
  public readonly ecsCluster: ECSCluster;
  public readonly videoBucket: S3Bucket;

  constructor(scope: Construct, id: string, props?: FireWatchStackProps) {
    super(scope, id, props);

    // ⚠️ COST WARNING: This stack creates resources that charge even when idle:
    // - MSK Serverless: ~$0 when idle (pay only for data)
    // - NAT Gateway: ~$32/month (1 gateway, charges per hour)
    // - VPC Endpoint: ~$7/month (saves money overall)
    // Minimum idle cost: ~$39/month
    // See docs/COST_OPTIMIZATION.md for cost optimization strategies

    // VPC for all resources
    // Using 1 NAT gateway by default for cost savings (pay-as-you-go optimization)
    // VPC endpoint for S3 will handle most traffic, reducing NAT gateway usage
    const natGatewayCount = props?.natGateways ?? 1;
    this.vpc = new ec2.Vpc(this, 'FireWatchVPC', {
      maxAzs: 3,
      natGateways: natGatewayCount,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
        },
        {
          cidrMask: 24,
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        },
        {
          cidrMask: 24,
          name: 'Isolated',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    // VPC Endpoint for S3 to reduce NAT gateway costs (pay-as-you-go optimization)
    // This allows ECS tasks to access S3 without going through NAT gateway
    // Cost: ~$7/month per endpoint (much cheaper than NAT gateway data transfer)
    // Gateway endpoints automatically work with all subnets in the VPC
    if (props?.enableS3VpcEndpoint !== false) {
      new ec2.GatewayVpcEndpoint(this, 'S3VpcEndpoint', {
        vpc: this.vpc,
        service: ec2.GatewayVpcEndpointAwsService.S3,
      });
    }

    // S3 bucket for video storage
    this.videoBucket = new S3Bucket(this, 'VideoBucket', {
      bucketName: props?.s3BucketName,
      enableEncryption: props?.enableS3Encryption ?? true,
    });

    // MSK Serverless Kafka cluster
    // Pay-as-you-go: Charges only for data ingested and stored, not broker-hours
    // Cost when idle: ~$0 (only pay for data retention if any)
    // Best for: Variable workloads, cost-conscious deployments
    this.mskCluster = new MSKServerlessCluster(this, 'MSKServerlessCluster', {
      vpc: this.vpc,
    });

    // ECS cluster for running containers
    this.ecsCluster = new ECSCluster(this, 'ECSCluster', {
      vpc: this.vpc,
      clusterName: props?.clusterName ?? 'firewatch-cluster',
      mskCluster: this.mskCluster,
      videoBucket: this.videoBucket,
    });

    // Outputs
    new cdk.CfnOutput(this, 'VPCId', {
      value: this.vpc.vpcId,
      description: 'VPC ID',
    });

    new cdk.CfnOutput(this, 'MSKClusterArn', {
      value: this.mskCluster.clusterArn,
      description: 'MSK Cluster ARN',
    });

    new cdk.CfnOutput(this, 'MSKBootstrapServers', {
      value: this.mskCluster.bootstrapServers,
      description: 'MSK Serverless Cluster ARN (use IAM auth)',
    });

    new cdk.CfnOutput(this, 'VideoBucketName', {
      value: this.videoBucket.bucket.bucketName,
      description: 'S3 Bucket for video storage',
    });

    new cdk.CfnOutput(this, 'ECSClusterName', {
      value: this.ecsCluster.cluster.clusterName,
      description: 'ECS Cluster Name',
    });
  }
}

