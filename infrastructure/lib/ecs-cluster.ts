import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { MSKServerlessCluster } from './msk-serverless-cluster';
import { S3Bucket } from './s3-bucket';
import { FireDetectionService } from './services/fire-detection-service';
import { S3UploadService } from './services/s3-upload-service';
import { VideoProducerService } from './services/video-producer-service';

export interface ECSClusterProps {
  vpc: ec2.Vpc;
  clusterName?: string;
  mskCluster: MSKServerlessCluster;
  videoBucket: S3Bucket;
}

export class ECSCluster extends Construct {
  public readonly cluster: ecs.Cluster;
  public readonly taskExecutionRole: iam.Role;
  public readonly taskRole: iam.Role;

  constructor(scope: Construct, id: string, props: ECSClusterProps) {
    super(scope, id);

    // ECS Cluster
    this.cluster = new ecs.Cluster(this, 'Cluster', {
      vpc: props.vpc,
      clusterName: props.clusterName ?? 'firewatch-cluster',
      containerInsights: true,
      // Enable Fargate Spot for cost savings (pay-as-you-go optimization)
      enableFargateCapacityProviders: true,
    });

    // Task Execution Role (for pulling images, writing logs)
    this.taskExecutionRole = new iam.Role(this, 'TaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Task Role (for application permissions)
    this.taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Grant S3 permissions
    props.videoBucket.bucket.grantReadWrite(this.taskRole);
    if (props.videoBucket.encryptionKey) {
      props.videoBucket.encryptionKey.grantEncryptDecrypt(this.taskRole);
    }

    // Security group for ECS tasks
    const ecsSecurityGroup = new ec2.SecurityGroup(this, 'ECSSecurityGroup', {
      vpc: props.vpc,
      description: 'Security group for ECS tasks',
      allowAllOutbound: true,
    });

    // Allow ECS tasks to access MSK Serverless (port 9098)
    props.mskCluster.securityGroup.addIngressRule(
      ec2.Peer.securityGroupId(ecsSecurityGroup.securityGroupId),
      ec2.Port.tcp(9098),
      'Allow ECS tasks to access MSK Serverless'
    );

    // Create ECR repositories (or reference existing ones)
    const fireDetectionRepo = new ecr.Repository(this, 'FireDetectionRepo', {
      repositoryName: 'firewatch/fire-detection-stream',
      imageScanOnPush: true,
      lifecycleRules: [
        {
          maxImageCount: 10,
        },
      ],
    });

    const s3UploadRepo = new ecr.Repository(this, 'S3UploadRepo', {
      repositoryName: 'firewatch/s3-upload-consumer',
      imageScanOnPush: true,
      lifecycleRules: [
        {
          maxImageCount: 10,
        },
      ],
    });

    const videoProducerRepo = new ecr.Repository(this, 'VideoProducerRepo', {
      repositoryName: 'firewatch/video-producer',
      imageScanOnPush: true,
      lifecycleRules: [
        {
          maxImageCount: 10,
        },
      ],
    });

    // Fire Detection Stream Service
    const fireDetectionService = new FireDetectionService(this, 'FireDetectionService', {
      cluster: this.cluster,
      taskExecutionRole: this.taskExecutionRole,
      taskRole: this.taskRole,
      repository: fireDetectionRepo,
      mskCluster: props.mskCluster,
      videoBucket: props.videoBucket,
    });

    // S3 Upload Consumer Service
    const s3UploadService = new S3UploadService(this, 'S3UploadService', {
      cluster: this.cluster,
      taskExecutionRole: this.taskExecutionRole,
      taskRole: this.taskRole,
      repository: s3UploadRepo,
      mskCluster: props.mskCluster,
      videoBucket: props.videoBucket,
    });

    // Video Producer Service (optional - can be run on-demand)
    const videoProducerService = new VideoProducerService(this, 'VideoProducerService', {
      cluster: this.cluster,
      taskExecutionRole: this.taskExecutionRole,
      taskRole: this.taskRole,
      repository: videoProducerRepo,
      mskCluster: props.mskCluster,
    });

    // Outputs
    new cdk.CfnOutput(this, 'FireDetectionServiceName', {
      value: fireDetectionService.service.serviceName,
      description: 'Fire Detection Stream Service Name',
    });

    new cdk.CfnOutput(this, 'S3UploadServiceName', {
      value: s3UploadService.service.serviceName,
      description: 'S3 Upload Consumer Service Name',
    });

    new cdk.CfnOutput(this, 'ECRRepositories', {
      value: `fire-detection: ${fireDetectionRepo.repositoryUri}, s3-upload: ${s3UploadRepo.repositoryUri}, producer: ${videoProducerRepo.repositoryUri}`,
      description: 'ECR Repository URIs',
    });
  }
}

