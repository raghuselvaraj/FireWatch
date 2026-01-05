import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as msk from 'aws-cdk-lib/aws-msk';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { IMSKCluster } from './msk-cluster-base';

export interface MSKServerlessClusterProps {
  vpc: ec2.Vpc;
}

export class MSKServerlessCluster extends Construct implements IMSKCluster {
  public readonly cluster: msk.CfnServerlessCluster;
  public readonly bootstrapServers: string;
  public readonly securityGroup: ec2.SecurityGroup;
  public readonly clusterArn: string;
  public readonly isServerless: boolean = true;

  constructor(scope: Construct, id: string, props: MSKServerlessClusterProps) {
    super(scope, id);

    // Security group for MSK Serverless
    this.securityGroup = new ec2.SecurityGroup(this, 'SecurityGroup', {
      vpc: props.vpc,
      description: 'Security group for MSK Serverless cluster',
      allowAllOutbound: true,
    });

    // Allow ECS tasks to access MSK Serverless
    // MSK Serverless uses port 9098 for IAM authentication
    this.securityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(9098), // MSK Serverless uses port 9098
      'Allow ECS tasks to access Kafka Serverless'
    );

    // MSK Serverless Cluster
    // Pay-as-you-go: Charges only for data ingested and stored, not broker-hours
    // Cost when idle: ~$0 (only pay for data retention if any)
    this.cluster = new msk.CfnServerlessCluster(this, 'Cluster', {
      clusterName: `${id.toLowerCase()}-serverless-cluster`,
      clientAuthentication: {
        sasl: {
          iam: {
            enabled: true, // Use IAM authentication for serverless
          },
        },
      },
      vpcConfig: {
        subnetIds: props.vpc.privateSubnets.map((subnet: ec2.ISubnet) => subnet.subnetId),
        securityGroupIds: [this.securityGroup.securityGroupId],
      },
    });

    // Bootstrap servers for MSK Serverless
    // Note: MSK Serverless uses IAM authentication and cluster ARN
    // The bootstrap servers format is: <cluster-arn>
    this.clusterArn = this.cluster.attrArn;
    this.bootstrapServers = this.clusterArn; // For serverless, use ARN as bootstrap

    // Output the bootstrap servers
    new cdk.CfnOutput(this, 'BootstrapServers', {
      value: this.cluster.attrArn,
      description: 'MSK Serverless Cluster ARN (use IAM auth)',
    });

    // Note: MSK Serverless uses IAM authentication instead of TLS
    // The bootstrap servers format is different - you'll need to use
    // the cluster ARN and IAM credentials
  }
}

