import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { S3Bucket } from '../lib/s3-bucket';

describe('S3Bucket', () => {
  let app: cdk.App;
  let stack: cdk.Stack;
  let template: Template;

  beforeEach(() => {
    app = new cdk.App();
    stack = new cdk.Stack(app, 'TestStack');
  });

  test('creates S3 bucket with encryption by default', () => {
    const bucket = new S3Bucket(stack, 'TestBucket');
    template = Template.fromStack(stack);

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
    });
  });

  test('creates KMS key when encryption is enabled', () => {
    const bucket = new S3Bucket(stack, 'TestBucket', {
      enableEncryption: true,
    });
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::KMS::Key', {
      Description: Match.stringLikeRegexp('.*FireWatch.*'),
      EnableKeyRotation: true,
    });

    expect(bucket.encryptionKey).toBeDefined();
  });

  test('uses S3-managed encryption when KMS is disabled', () => {
    const bucket = new S3Bucket(stack, 'TestBucket', {
      enableEncryption: false,
    });
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          {
            ServerSideEncryptionByDefault: {
              SSEAlgorithm: 'AES256',
            },
          },
        ],
      },
    });

    expect(bucket.encryptionKey).toBeUndefined();
  });

  test('enables versioning', () => {
    const bucket = new S3Bucket(stack, 'TestBucket');
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      VersioningConfiguration: {
        Status: 'Enabled',
      },
    });
  });

  test('blocks all public access', () => {
    const bucket = new S3Bucket(stack, 'TestBucket');
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  test('configures lifecycle rules', () => {
    const bucket = new S3Bucket(stack, 'TestBucket');
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      LifecycleConfiguration: {
        Rules: Match.arrayWith([
          Match.objectLike({
            Id: 'DeleteOldVersions',
            Status: 'Enabled',
            NoncurrentVersionExpirationInDays: 90,
          }),
          Match.objectLike({
            Id: 'TransitionToIA',
            Status: 'Enabled',
            Transitions: Match.arrayWith([
              Match.objectLike({
                StorageClass: 'STANDARD_IA',
                TransitionInDays: 30,
              }),
              Match.objectLike({
                StorageClass: 'GLACIER',
                TransitionInDays: 90,
              }),
            ]),
          }),
        ]),
      },
    });
  });

  test('configures CORS', () => {
    const bucket = new S3Bucket(stack, 'TestBucket');
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      CorsConfiguration: {
        CorsRules: Match.arrayWith([
          Match.objectLike({
            AllowedOrigins: ['*'],
            AllowedMethods: ['GET', 'HEAD'],
            AllowedHeaders: ['*'],
            MaxAge: 3000,
          }),
        ]),
      },
    });
  });

  test('uses custom bucket name when provided', () => {
    const bucket = new S3Bucket(stack, 'TestBucket', {
      bucketName: 'my-custom-bucket-name',
    });
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketName: 'my-custom-bucket-name',
    });
  });

  test('bucket has RETAIN removal policy', () => {
    const bucket = new S3Bucket(stack, 'TestBucket');
    template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::S3::Bucket', {
      DeletionPolicy: 'Retain',
      UpdateReplacePolicy: 'Retain',
    });
  });

  test('exposes bucket reference', () => {
    const bucket = new S3Bucket(stack, 'TestBucket');
    expect(bucket.bucket).toBeDefined();
    expect(bucket.bucket.bucketName).toBeDefined();
  });
});

