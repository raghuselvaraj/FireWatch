import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { MSKServerlessCluster } from '../msk-serverless-cluster';
import { S3Bucket } from '../s3-bucket';

export interface FireDetectionServiceProps {
  cluster: ecs.Cluster;
  taskExecutionRole: iam.Role;
  taskRole: iam.Role;
  repository: ecr.Repository;
  mskCluster: MSKServerlessCluster;
  videoBucket: S3Bucket;
}

export class FireDetectionService extends Construct {
  public readonly service: ecs.FargateService;
  public readonly taskDefinition: ecs.FargateTaskDefinition;

  constructor(scope: Construct, id: string, props: FireDetectionServiceProps) {
    super(scope, id);

    // Task Definition
    this.taskDefinition = new ecs.FargateTaskDefinition(this, 'TaskDefinition', {
      memoryLimitMiB: 4096,
      cpu: 2048,
      executionRole: props.taskExecutionRole,
      taskRole: props.taskRole,
    });

    // Log Group
    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/firewatch/fire-detection-stream`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Container
    const container = this.taskDefinition.addContainer('FireDetectionContainer', {
      image: ecs.ContainerImage.fromEcrRepository(props.repository, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'fire-detection',
        logGroup,
      }),
      environment: {
        KAFKA_BOOTSTRAP_SERVERS: props.mskCluster.bootstrapServers,
        KAFKA_USE_IAM_AUTH: 'true',
        KAFKA_VIDEO_TOPIC: 'video-frames',
        KAFKA_DETECTIONS_TOPIC: 'fire-detections',
        KAFKA_VIDEO_COMPLETIONS_TOPIC: 'video-completions',
        KAFKA_GROUP_ID: 'fire-detection-stream',
        ML_MODEL_TYPE: 'fire-detect-nn',
        ML_MODEL_SOURCE: 'fire-detect-nn',
        CONFIDENCE_THRESHOLD: '0.5',
        CLIP_STORAGE_PATH: '/tmp/clips',
        CLIP_HEATMAP_OVERLAY_ALPHA: '0.4',
        S3_BUCKET: props.videoBucket.bucket.bucketName,
        AWS_REGION: cdk.Stack.of(this).region,
      },
      healthCheck: {
        command: ['CMD-SHELL', 'python3 -c "import sys; sys.exit(0)" || exit 1'],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
    });

    // Service
    this.service = new ecs.FargateService(this, 'Service', {
      cluster: props.cluster,
      taskDefinition: this.taskDefinition,
      desiredCount: 2, // Scale horizontally
      assignPublicIp: false,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      },
      healthCheckGracePeriod: cdk.Duration.seconds(60),
      capacityProviderStrategies: [
        {
          capacityProvider: 'FARGATE_SPOT',
          weight: 3, // Prefer Spot (70% discount)
        },
        {
          capacityProvider: 'FARGATE',
          weight: 1, // Fallback to regular Fargate
        },
      ],
    });

    // Auto Scaling
    const scaling = this.service.autoScaleTaskCount({
      minCapacity: 1,
      maxCapacity: 10,
    });

    scaling.scaleOnCpuUtilization('CpuScaling', {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });

    scaling.scaleOnMemoryUtilization('MemoryScaling', {
      targetUtilizationPercent: 80,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });
  }
}

