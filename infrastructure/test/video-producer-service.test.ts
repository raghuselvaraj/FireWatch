import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { VideoProducerService } from '../lib/services/video-producer-service';
import { MSKServerlessCluster } from '../lib/msk-serverless-cluster';

describe('VideoProducerService', () => {
  let app: cdk.App;
  let stack: cdk.Stack;
  let vpc: ec2.Vpc;
  let cluster: ecs.Cluster;
  let taskExecutionRole: iam.Role;
  let taskRole: iam.Role;
  let repository: ecr.Repository;
  let mskCluster: MSKServerlessCluster;
  let service: VideoProducerService;
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
    
    service = new VideoProducerService(stack, 'TestService', {
      cluster,
      taskExecutionRole,
      taskRole,
      repository,
      mskCluster,
    });
    
    template = Template.fromStack(stack);
  });

  test('creates Fargate task definition with correct resources', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Family: Match.stringLikeRegexp('.*TestService.*'),
      NetworkMode: 'awsvpc',
      RequiresCompatibilities: ['FARGATE'],
      Cpu: '512',
      Memory: '1024',
    });
  });

  test('configures container with correct environment variables', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Name: 'VideoProducerContainer',
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
              Name: 'FRAME_EXTRACTION_INTERVAL',
              Value: '1',
            }),
            Match.objectLike({
              Name: 'FRAME_WIDTH',
              Value: '640',
            }),
            Match.objectLike({
              Name: 'FRAME_HEIGHT',
              Value: '480',
            }),
          ]),
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
              'awslogs-group': '/firewatch/video-producer',
              'awslogs-stream-prefix': 'video-producer',
            }),
          },
        }),
      ]),
    });
  });

  test('does not create ECS service (designed for one-off tasks)', () => {
    const services = template.findResources('AWS::ECS::Service');
    const producerServices = Object.values(services).filter(
      (service: any) => service.Properties?.ServiceName?.includes('TestService')
    );
    expect(producerServices.length).toBe(0);
  });

  test('exposes task definition', () => {
    expect(service.taskDefinition).toBeDefined();
  });
});

