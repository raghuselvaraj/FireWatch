import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { FireDetectionService } from '../lib/services/fire-detection-service';
import { MSKServerlessCluster } from '../lib/msk-serverless-cluster';
import { S3Bucket } from '../lib/s3-bucket';

describe('FireDetectionService', () => {
  let app: cdk.App;
  let stack: cdk.Stack;
  let vpc: ec2.Vpc;
  let cluster: ecs.Cluster;
  let taskExecutionRole: iam.Role;
  let taskRole: iam.Role;
  let repository: ecr.Repository;
  let mskCluster: MSKServerlessCluster;
  let videoBucket: S3Bucket;
  let service: FireDetectionService;
  let template: Template;

  beforeEach(() => {
    app = new cdk.App();
    stack = new cdk.Stack(app, 'TestStack');
    vpc = new ec2.Vpc(stack, 'TestVPC', { maxAzs: 2 });
    cluster = new ecs.Cluster(stack, 'TestCluster', { vpc });
    taskExecutionRole = new iam.Role(stack, 'TaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    taskRole = new iam.Role(stack, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    repository = new ecr.Repository(stack, 'TestRepo');
    mskCluster = new MSKServerlessCluster(stack, 'TestMSK', { vpc });
    videoBucket = new S3Bucket(stack, 'TestBucket');
    
    service = new FireDetectionService(stack, 'TestService', {
      cluster,
      taskExecutionRole,
      taskRole,
      repository,
      mskCluster,
      videoBucket,
    });
    
    template = Template.fromStack(stack);
  });

  test('creates Fargate task definition with correct resources', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Family: Match.stringLikeRegexp('.*TestService.*'),
      NetworkMode: 'awsvpc',
      RequiresCompatibilities: ['FARGATE'],
      Cpu: '2048',
      Memory: '4096',
    });
  });

  test('creates Fargate service with correct configuration', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      ServiceName: Match.stringLikeRegexp('.*TestService.*'),
      LaunchType: 'FARGATE',
      DesiredCount: 2,
      NetworkConfiguration: {
        AwsvpcConfiguration: {
          AssignPublicIp: 'DISABLED',
          Subnets: Match.anyValue(),
          SecurityGroups: Match.anyValue(),
        },
      },
    });
  });

  test('configures container with correct environment variables', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Name: 'FireDetectionContainer',
          Environment: Match.arrayWith([
            Match.objectLike({
              Name: 'KAFKA_USE_IAM_AUTH',
              Value: 'true',
            }),
            Match.objectLike({
              Name: 'KAFKA_VIDEO_TOPIC',
              Value: 'video-frames',
            }),
            Match.objectLike({
              Name: 'KAFKA_DETECTIONS_TOPIC',
              Value: 'fire-detections',
            }),
            Match.objectLike({
              Name: 'ML_MODEL_TYPE',
              Value: 'fire-detect-nn',
            }),
            Match.objectLike({
              Name: 'CONFIDENCE_THRESHOLD',
              Value: '0.5',
            }),
          ]),
        }),
      ]),
    });
  });

  test('configures health check', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          HealthCheck: {
            Command: Match.arrayWith(['CMD-SHELL', Match.anyValue()]),
            Interval: 30,
            Timeout: 5,
            Retries: 3,
            StartPeriod: 60,
          },
        }),
      ]),
    });
  });

  test('configures CloudWatch logging', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          LogConfiguration: {
            LogDriver: 'awslogs',
            Options: Match.objectLike({
              'awslogs-group': '/firewatch/fire-detection-stream',
              'awslogs-stream-prefix': 'fire-detection',
            }),
          },
        }),
      ]),
    });
  });

  test('configures auto-scaling', () => {
    template.hasResourceProperties('AWS::ApplicationAutoScaling::ScalableTarget', {
      ServiceNamespace: 'ecs',
      ScalableDimension: 'ecs:service:DesiredCount',
      MinCapacity: 1,
      MaxCapacity: 10,
    });
  });

  test('configures CPU-based scaling', () => {
    template.hasResourceProperties('AWS::ApplicationAutoScaling::ScalingPolicy', {
      PolicyType: 'TargetTrackingScaling',
      TargetTrackingScalingPolicyConfiguration: Match.objectLike({
        PredefinedMetricSpecification: {
          PredefinedMetricType: 'ECSServiceAverageCPUUtilization',
        },
        TargetValue: 70,
        ScaleInCooldown: 60,
        ScaleOutCooldown: 60,
      }),
    });
  });

  test('configures memory-based scaling', () => {
    template.hasResourceProperties('AWS::ApplicationAutoScaling::ScalingPolicy', {
      PolicyType: 'TargetTrackingScaling',
      TargetTrackingScalingPolicyConfiguration: Match.objectLike({
        PredefinedMetricSpecification: {
          PredefinedMetricType: 'ECSServiceAverageMemoryUtilization',
        },
        TargetValue: 80,
      }),
    });
  });

  test('uses Fargate Spot for cost savings', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      CapacityProviderStrategy: Match.arrayWith([
        Match.objectLike({
          CapacityProvider: 'FARGATE_SPOT',
          Weight: 3,
        }),
        Match.objectLike({
          CapacityProvider: 'FARGATE',
          Weight: 1,
        }),
      ]),
    });
  });

  test('exposes service and task definition', () => {
    expect(service.service).toBeDefined();
    expect(service.taskDefinition).toBeDefined();
  });
});

