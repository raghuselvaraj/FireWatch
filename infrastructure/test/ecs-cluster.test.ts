import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { ECSCluster } from '../lib/ecs-cluster';
import { MSKServerlessCluster } from '../lib/msk-serverless-cluster';
import { S3Bucket } from '../lib/s3-bucket';

describe('ECSCluster', () => {
  let app: cdk.App;
  let stack: cdk.Stack;
  let vpc: ec2.Vpc;
  let mskCluster: MSKServerlessCluster;
  let videoBucket: S3Bucket;
  let ecsCluster: ECSCluster;
  let template: Template;

  beforeEach(() => {
    app = new cdk.App();
    stack = new cdk.Stack(app, 'TestStack');
    vpc = new ec2.Vpc(stack, 'TestVPC', {
      maxAzs: 2,
    });
    mskCluster = new MSKServerlessCluster(stack, 'TestMSK', { vpc });
    videoBucket = new S3Bucket(stack, 'TestBucket');
    ecsCluster = new ECSCluster(stack, 'TestECS', {
      vpc,
      mskCluster,
      videoBucket,
      clusterName: 'test-cluster',
    });
    template = Template.fromStack(stack);
  });

  test('creates ECS cluster with correct name', () => {
    template.hasResourceProperties('AWS::ECS::Cluster', {
      ClusterName: 'test-cluster',
      ClusterSettings: Match.arrayWith([
        Match.objectLike({
          Name: 'containerInsights',
          Value: 'enabled',
        }),
      ]),
    });
  });

  test('creates task execution role', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'sts:AssumeRole',
            Effect: 'Allow',
            Principal: {
              Service: 'ecs-tasks.amazonaws.com',
            },
          }),
        ]),
      },
      ManagedPolicyArns: Match.arrayWith([
        Match.stringLikeRegexp('.*AmazonECSTaskExecutionRolePolicy.*'),
      ]),
    });
  });

  test('creates task role', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'sts:AssumeRole',
            Effect: 'Allow',
            Principal: {
              Service: 'ecs-tasks.amazonaws.com',
            },
          }),
        ]),
      },
    });
  });

  test('grants S3 permissions to task role', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              's3:GetObject*',
              's3:PutObject*',
              's3:DeleteObject*',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  test('creates ECR repositories', () => {
    template.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'firewatch/fire-detection-stream',
      ImageScanningConfiguration: {
        ScanOnPush: true,
      },
      LifecyclePolicy: {
        LifecyclePolicyText: Match.stringLikeRegexp('.*maxImageCount.*10.*'),
      },
    });

    template.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'firewatch/s3-upload-consumer',
    });

    template.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'firewatch/video-producer',
    });
  });

  test('creates fire detection service', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      ServiceName: Match.stringLikeRegexp('.*FireDetectionService.*'),
      LaunchType: 'FARGATE',
      DesiredCount: 2,
    });
  });

  test('creates S3 upload service', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      ServiceName: Match.stringLikeRegexp('.*S3UploadService.*'),
      LaunchType: 'FARGATE',
      DesiredCount: 2,
    });
  });

  test('creates video producer task definition', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Family: Match.stringLikeRegexp('.*VideoProducerService.*'),
      NetworkMode: 'awsvpc',
      RequiresCompatibilities: ['FARGATE'],
    });
  });

  test('configures Fargate Spot for cost savings', () => {
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

  test('creates auto-scaling for services', () => {
    template.hasResourceProperties('AWS::ApplicationAutoScaling::ScalableTarget', {
      ServiceNamespace: 'ecs',
      ScalableDimension: 'ecs:service:DesiredCount',
      MinCapacity: 1,
    });
  });

  test('creates CloudWatch log groups', () => {
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: '/firewatch/fire-detection-stream',
      RetentionInDays: 7,
    });

    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: '/firewatch/s3-upload-consumer',
    });

    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: '/firewatch/video-producer',
    });
  });

  test('creates CloudFormation outputs', () => {
    template.hasOutput('FireDetectionServiceName', {
      Value: Match.anyValue(),
    });

    template.hasOutput('S3UploadServiceName', {
      Value: Match.anyValue(),
    });

    template.hasOutput('ECRRepositories', {
      Value: Match.stringLikeRegexp('.*fire-detection.*s3-upload.*producer.*'),
    });
  });

  test('exposes cluster reference', () => {
    expect(ecsCluster.cluster).toBeDefined();
    expect(ecsCluster.cluster.clusterName).toBe('test-cluster');
  });

  test('exposes task roles', () => {
    expect(ecsCluster.taskExecutionRole).toBeDefined();
    expect(ecsCluster.taskRole).toBeDefined();
  });
});

