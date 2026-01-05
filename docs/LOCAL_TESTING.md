# Local Testing Guide

Yes! You can test the entire Kafka stack locally using Docker Compose. This is the simplest way to test before deploying to AWS.

## Quick Start

### 1. Start Local Kafka Stack

```bash
# Start Kafka, Zookeeper, and Kafka UI
docker-compose up -d
```

This starts:
- **Zookeeper** (port 2181)
- **Kafka** (port 9092)
- **Kafka UI** (http://localhost:8081) - Web interface to monitor topics

### 2. Create Kafka Topics

```bash
./scripts/setup_kafka_topics.sh
```

This creates:
- `video-frames` (6 partitions)
- `fire-detections` (6 partitions)
- `video-completions` (3 partitions)

### 3. Run the Complete Test

```bash
./scripts/run_full_test.sh
```

This script:
1. ✅ Checks if Kafka is running (starts it if needed)
2. ✅ Creates Kafka topics
3. ✅ Starts the fire detection stream processor
4. ✅ Processes all videos in `test_files/`
5. ✅ Shows real-time processing status
6. ✅ Monitors completion and shows results

## Manual Step-by-Step Testing

If you prefer to run components separately:

### Terminal 1: Start Kafka (if not already running)

```bash
docker-compose up -d
```

Verify it's running:
```bash
docker-compose ps
```

Access Kafka UI: **http://localhost:8081**

### Terminal 2: Start Fire Detection Stream

```bash
python3 streams/fire_detection_stream.py
```

You should see:
```
Fire detection model initialized: fire-detect-nn (DenseNet121)
Starting fire detection stream processor...
Consuming from topic: video-frames
Publishing to topic: fire-detections
```

### Terminal 3: Start S3 Upload Consumer (Optional)

```bash
python3 consumer/s3_video_consumer.py
```

**Note**: If S3 is not configured, this will skip S3 uploads but still process videos locally.

### Terminal 4: Process Test Videos

```bash
python3 scripts/test_with_videos.py
```

Or process a specific video:
```bash
python3 producer/video_producer.py test_files/trail_cams/actual_fires/fire_test_1.mp4 fire_test_1
```

## What Gets Tested Locally

### ✅ Works Exactly Like Production

1. **Kafka Topics**: Same topics and partitions as production
2. **Message Format**: Same JSON message structure
3. **ML Model**: Same fire-detect-nn model with GradCAM
4. **Video Processing**: Same frame extraction and overlay logic
5. **Consumer Groups**: Same consumer group behavior

### ⚠️ Differences from Production

1. **Kafka**: Local Docker Compose vs AWS MSK
   - Same Kafka protocol, different infrastructure
   - Local: Single broker, no replication
   - Production: Multi-broker, replicated, high availability

2. **S3 Uploads**: Optional locally
   - Can skip S3 if not configured
   - Videos saved locally in `clips/` directory
   - Production: Always uploads to S3

3. **Scaling**: Single instance locally
   - Local: One stream processor
   - Production: Multiple ECS tasks (horizontal scaling)

## Local vs Production Comparison

| Component | Local (Docker Compose) | Production (AWS MSK) |
|-----------|----------------------|---------------------|
| **Kafka** | Single broker, no replication | Multi-broker, replicated, HA |
| **Zookeeper** | Docker container | AWS managed (or KRaft) |
| **Monitoring** | Kafka UI (localhost:8081) | CloudWatch + MSK metrics |
| **Scaling** | Manual (single instance) | Automatic (ECS auto-scaling) |
| **Storage** | Local filesystem | S3 bucket |
| **Cost** | Free (local) | Pay-as-you-go |

## Test Video Structure

Your test videos should be organized as:

```
test_files/
├── trail_cams/
│   ├── actual_fires/
│   │   └── fire_test_1.mp4
│   └── no_fires/
│       └── no_fire_test_1.mp4
└── fire_tower_cams/
    └── ...
```

The test script automatically finds and processes all videos in this structure.

## Monitoring Local Kafka

### Kafka UI (Web Interface)

Open in browser: **http://localhost:8081**

Features:
- View all topics and partitions
- Browse messages
- Monitor consumer groups
- View topic configurations

### Command Line

```bash
# List topics
docker exec -it firewatch-kafka-1 kafka-topics.sh --list --bootstrap-server localhost:9092

# View messages in a topic
docker exec -it firewatch-kafka-1 kafka-console-consumer.sh \
  --topic video-frames \
  --from-beginning \
  --bootstrap-server localhost:9092

# Check consumer group status
docker exec -it firewatch-kafka-1 kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --group fire-detection-stream \
  --describe
```

## Troubleshooting

### Kafka Not Starting

```bash
# Check if ports are in use
lsof -i :9092
lsof -i :2181

# Stop and restart
docker-compose down
docker-compose up -d
```

### Can't Connect to Kafka

```bash
# Check Kafka is running
docker-compose ps

# Check logs
docker-compose logs kafka

# Verify connection
python3 -c "from kafka import KafkaProducer; p = KafkaProducer(bootstrap_servers='localhost:9092'); p.close(); print('Connected!')"
```

### Topics Not Created

```bash
# Manually create topics
./scripts/setup_kafka_topics.sh

# Or manually:
docker exec -it firewatch-kafka-1 kafka-topics.sh \
  --create \
  --topic video-frames \
  --bootstrap-server localhost:9092 \
  --partitions 6 \
  --replication-factor 1
```

### Stream Processor Not Processing

1. Check logs: `logs/stream.log`
2. Verify Kafka connection: `python3 scripts/check_kafka_status.py`
3. Check consumer group: Use Kafka UI or command line tools
4. Reset offsets if needed: `./scripts/reset_consumer_offsets.sh`

## Cleanup

```bash
# Stop all containers
docker-compose down

# Remove all data (topics, messages, etc.)
docker-compose down -v

# Remove local video outputs
rm -rf clips/
rm -rf logs/
```

## Next Steps

Once local testing works:
1. ✅ Verify ML model accuracy
2. ✅ Test with different video types
3. ✅ Verify heatmap overlays
4. ✅ Test consumer group behavior
5. ✅ Deploy to AWS MSK for production

## Summary

**Yes, it's that simple!** 

1. `docker-compose up -d` - Start Kafka
2. `./scripts/run_full_test.sh` - Run everything
3. Check results in `clips/` directory

The local setup uses the **exact same code** as production - only the Kafka infrastructure differs (Docker Compose vs AWS MSK). This makes local testing a perfect way to validate your pipeline before deploying to AWS.

