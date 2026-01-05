import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { MSKServerlessCluster } from '../msk-serverless-cluster';

export interface VideoProducerServiceProps {
  cluster: ecs.Cluster;
  taskExecutionRole: iam.Role;
  taskRole: iam.Role;
  repository: ecr.Repository;
  mskCluster: MSKServerlessCluster;
}

export class VideoProducerService extends Construct {
  public readonly taskDefinition: ecs.FargateTaskDefinition;

  constructor(scope: Construct, id: string, props: VideoProducerServiceProps) {
    super(scope, id);

    // Task Definition (can be run as one-off tasks)
    this.taskDefinition = new ecs.FargateTaskDefinition(this, 'TaskDefinition', {
      memoryLimitMiB: 1024,
      cpu: 512,
      executionRole: props.taskExecutionRole,
      taskRole: props.taskRole,
    });

    // Log Group
    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/firewatch/video-producer`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Container
    this.taskDefinition.addContainer('VideoProducerContainer', {
      image: ecs.ContainerImage.fromEcrRepository(props.repository, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'video-producer',
        logGroup,
      }),
      environment: {
        KAFKA_BOOTSTRAP_SERVERS: props.mskCluster.bootstrapServers,
        KAFKA_USE_IAM_AUTH: 'true',
        KAFKA_VIDEO_TOPIC: 'video-frames',
        FRAME_EXTRACTION_INTERVAL: '1',
        FRAME_WIDTH: '640',
        FRAME_HEIGHT: '480',
        AWS_REGION: cdk.Stack.of(this).region,
      },
    });

    // Note: This service is designed to run as one-off tasks
    // Use ECS RunTask API or CLI to trigger video processing
  }
}

