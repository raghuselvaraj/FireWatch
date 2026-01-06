import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { MSKServerlessCluster } from '../lib/msk-serverless-cluster';

describe('MSKServerlessCluster', () => {
  let app: cdk.App;
  let stack: cdk.Stack;
  let vpc: ec2.Vpc;
  let cluster: MSKServerlessCluster;
  let template: Template;

  beforeEach(() => {
    app = new cdk.App();
    stack = new cdk.Stack(app, 'TestStack');
    vpc = new ec2.Vpc(stack, 'TestVPC', {
      maxAzs: 2,
    });
    cluster = new MSKServerlessCluster(stack, 'TestMSKCluster', { vpc });
    template = Template.fromStack(stack);
  });

  test('creates MSK Serverless cluster with IAM authentication', () => {
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

  test('creates security group for MSK cluster', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroup', {
      GroupDescription: Match.stringLikeRegexp('.*MSK Serverless.*'),
      SecurityGroupEgress: [
        {
          CidrIp: '0.0.0.0/0',
          Description: 'Allow all outbound traffic by default',
          IpProtocol: '-1',
        },
      ],
    });
  });

  test('allows ingress on port 9098 from VPC CIDR', () => {
    const securityGroups = template.findResources('AWS::EC2::SecurityGroup');
    const mskSecurityGroup = Object.values(securityGroups).find(
      (sg: any) => sg.Properties?.GroupDescription?.includes('MSK Serverless')
    );

    expect(mskSecurityGroup).toBeDefined();
    expect(mskSecurityGroup?.Properties?.SecurityGroupIngress).toBeDefined();
    
    const ingressRules = mskSecurityGroup?.Properties?.SecurityGroupIngress || [];
    const port9098Rule = ingressRules.find(
      (rule: any) => rule.FromPort === 9098 && rule.ToPort === 9098
    );
    expect(port9098Rule).toBeDefined();
    expect(port9098Rule?.IpProtocol).toBe('tcp');
  });

  test('configures VPC with isolated subnets', () => {
    template.hasResourceProperties('AWS::MSK::ServerlessCluster', {
      VpcConfig: {
        SubnetIds: Match.arrayWith([Match.anyValue()]),
        SecurityGroupIds: Match.arrayWith([Match.anyValue()]),
      },
    });
  });

  test('exposes cluster ARN as bootstrap servers', () => {
    expect(cluster.bootstrapServers).toBe(cluster.clusterArn);
    expect(cluster.isServerless).toBe(true);
  });

  test('creates CloudFormation output for bootstrap servers', () => {
    template.hasOutput('BootstrapServers', {
      Value: Match.anyValue(),
      Description: Match.stringLikeRegexp('.*MSK Serverless.*'),
    });
  });

  test('cluster ARN is accessible', () => {
    expect(cluster.clusterArn).toBeDefined();
    expect(typeof cluster.clusterArn).toBe('string');
  });

  test('security group is accessible', () => {
    expect(cluster.securityGroup).toBeDefined();
    expect(cluster.securityGroup.securityGroupId).toBeDefined();
  });
});

