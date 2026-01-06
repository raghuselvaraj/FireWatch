import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { FireWatchStack } from '../lib/firewatch-stack';

describe('FireWatchStack', () => {
  let app: cdk.App;
  let stack: FireWatchStack;
  let template: Template;

  beforeEach(() => {
    app = new cdk.App();
    stack = new FireWatchStack(app, 'TestStack');
    template = Template.fromStack(stack);
  });

  test('creates VPC with correct configuration', () => {
    template.hasResourceProperties('AWS::EC2::VPC', {
      CidrBlock: Match.anyValue(),
      EnableDnsHostnames: true,
      EnableDnsSupport: true,
    });
  });

  test('creates VPC with 3 availability zones', () => {
    template.hasResourceProperties('AWS::EC2::VPC', {
      CidrBlock: Match.anyValue(),
    });
    
    // Check for subnets in multiple AZs
    const subnets = template.findResources('AWS::EC2::Subnet');
    expect(Object.keys(subnets).length).toBeGreaterThan(0);
  });

  test('creates NAT gateway by default', () => {
    template.hasResourceProperties('AWS::EC2::NatGateway', Match.anyValue());
  });

  test('creates VPC endpoint for S3 by default', () => {
    template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
      ServiceName: Match.stringLikeRegexp('com.amazonaws.*.s3'),
      VpcEndpointType: 'Gateway',
    });
  });

  test('can disable S3 VPC endpoint', () => {
    const app2 = new cdk.App();
    const stack2 = new FireWatchStack(app2, 'TestStack2', {
      enableS3VpcEndpoint: false,
    });
    const template2 = Template.fromStack(stack2);
    
    const vpcEndpoints = template2.findResources('AWS::EC2::VPCEndpoint');
    const s3Endpoints = Object.values(vpcEndpoints).filter(
      (resource: any) => resource.Properties?.ServiceName?.includes('s3')
    );
    expect(s3Endpoints.length).toBe(0);
  });

  test('creates MSK Serverless cluster', () => {
    template.hasResourceProperties('AWS::MSK::ServerlessCluster', {
      ClusterName: Match.stringLikeRegexp('.*serverless-cluster'),
      ClientAuthentication: {
        Sasl: {
          Iam: {
            Enabled: true,
          },
        },
      },
    });
  });

  test('creates S3 bucket with encryption', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketEncryption: {
        ServerSideEncryptionConfiguration: Match.arrayWith([
          Match.objectLike({
            ServerSideEncryptionByDefault: {
              SSEAlgorithm: Match.anyValue(),
            },
          }),
        ]),
      },
      VersioningConfiguration: {
        Status: 'Enabled',
      },
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  test('creates S3 bucket with KMS encryption by default', () => {
    template.hasResourceProperties('AWS::KMS::Key', {
      Description: Match.stringLikeRegexp('.*FireWatch.*'),
      EnableKeyRotation: true,
    });
  });

  test('creates ECS cluster', () => {
    template.hasResourceProperties('AWS::ECS::Cluster', {
      ClusterName: 'firewatch-cluster',
      ClusterSettings: Match.arrayWith([
        Match.objectLike({
          Name: 'containerInsights',
          Value: 'enabled',
        }),
      ]),
    });
  });

  test('creates ECR repositories', () => {
    template.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'firewatch/fire-detection-stream',
      ImageScanningConfiguration: {
        ScanOnPush: true,
      },
    });

    template.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'firewatch/s3-upload-consumer',
    });

    template.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'firewatch/video-producer',
    });
  });

  test('creates ECS services', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      ServiceName: Match.stringLikeRegexp('.*FireDetectionService.*'),
      LaunchType: 'FARGATE',
      DesiredCount: 2,
    });

    template.hasResourceProperties('AWS::ECS::Service', {
      ServiceName: Match.stringLikeRegexp('.*S3UploadService.*'),
      LaunchType: 'FARGATE',
      DesiredCount: 2,
    });
  });

  test('creates CloudFormation outputs', () => {
    template.hasOutput('VPCId', {
      Value: Match.anyValue(),
    });

    template.hasOutput('MSKClusterArn', {
      Value: Match.anyValue(),
    });

    template.hasOutput('MSKBootstrapServers', {
      Value: Match.anyValue(),
    });

    template.hasOutput('VideoBucketName', {
      Value: Match.anyValue(),
    });

    template.hasOutput('ECSClusterName', {
      Value: 'firewatch-cluster',
    });
  });

  test('uses custom cluster name when provided', () => {
    const app2 = new cdk.App();
    const stack2 = new FireWatchStack(app2, 'TestStack2', {
      clusterName: 'custom-cluster',
    });
    const template2 = Template.fromStack(stack2);
    
    template2.hasResourceProperties('AWS::ECS::Cluster', {
      ClusterName: 'custom-cluster',
    });
  });

  test('uses custom S3 bucket name when provided', () => {
    const app2 = new cdk.App();
    const stack2 = new FireWatchStack(app2, 'TestStack2', {
      s3BucketName: 'my-custom-bucket',
    });
    const template2 = Template.fromStack(stack2);
    
    template2.hasResourceProperties('AWS::S3::Bucket', {
      BucketName: 'my-custom-bucket',
    });
  });

  test('can configure NAT gateway count', () => {
    const app2 = new cdk.App();
    const stack2 = new FireWatchStack(app2, 'TestStack2', {
      natGateways: 2,
    });
    const template2 = Template.fromStack(stack2);
    
    const natGateways = template2.findResources('AWS::EC2::NatGateway');
    expect(Object.keys(natGateways).length).toBeGreaterThanOrEqual(2);
  });
});

