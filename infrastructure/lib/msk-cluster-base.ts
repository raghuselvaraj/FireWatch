import * as ec2 from 'aws-cdk-lib/aws-ec2';

/**
 * Interface for MSK Serverless cluster
 */
export interface IMSKCluster {
  readonly securityGroup: ec2.SecurityGroup;
  readonly bootstrapServers: string;
  readonly clusterArn: string;
  readonly isServerless: boolean;
}

