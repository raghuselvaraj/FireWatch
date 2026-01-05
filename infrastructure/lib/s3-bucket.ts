import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';

export interface S3BucketProps {
  bucketName?: string;
  enableEncryption?: boolean;
}

export class S3Bucket extends Construct {
  public readonly bucket: s3.Bucket;
  public readonly encryptionKey?: kms.Key;

  constructor(scope: Construct, id: string, props?: S3BucketProps) {
    super(scope, id);

    // KMS key for encryption
    if (props?.enableEncryption ?? true) {
      this.encryptionKey = new kms.Key(this, 'EncryptionKey', {
        description: 'KMS key for FireWatch video bucket encryption',
        enableKeyRotation: true,
      });
    }

    // S3 bucket for video storage
    this.bucket = new s3.Bucket(this, 'Bucket', {
      bucketName: props?.bucketName,
      encryption: this.encryptionKey
        ? s3.BucketEncryption.KMS
        : s3.BucketEncryption.S3_MANAGED,
      encryptionKey: this.encryptionKey,
      versioned: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
      lifecycleRules: [
        {
          id: 'DeleteOldVersions',
          enabled: true,
          noncurrentVersionExpiration: cdk.Duration.days(90),
        },
        {
          id: 'TransitionToIA',
          enabled: true,
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(30),
            },
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
      ],
    });

    // Add CORS configuration for web access if needed
    this.bucket.addCorsRule({
      allowedOrigins: ['*'],
      allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.HEAD],
      allowedHeaders: ['*'],
      maxAge: 3000,
    });
  }
}

