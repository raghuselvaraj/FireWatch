#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { FireWatchStack } from '../lib/firewatch-stack';

const app = new cdk.App();

new FireWatchStack(app, 'FireWatchStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
  },
  description: 'FireWatch - Real-time forest fire detection using Kafka and ML',
  // Pay-as-you-go optimizations
  natGateways: app.node.tryGetContext('natGateways') || 1, // Default to 1 for cost savings
  enableS3VpcEndpoint: app.node.tryGetContext('enableS3VpcEndpoint') !== false, // Default to true
});

app.synth();

