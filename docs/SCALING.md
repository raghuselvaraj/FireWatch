# Horizontal Scaling Guide

FireWatch is designed to scale horizontally to process multiple videos simultaneously at 20-30 frames per second.

## Architecture for Scaling

```
Multiple Producers → Kafka (Partitioned Topics) → Multiple Stream Processors
                                                          ↓
                                            Kafka (video-completions topic)
                                                          ↓
                                            Multiple S3 Upload Consumers → S3
```

### Key Scaling Features

1. **Partitioned Topics**: Kafka topics are partitioned to allow parallel processing
2. **Consumer Groups**: Multiple stream processors share partitions via consumer groups
3. **Video ID Partitioning**: Frames from the same video always go to the same partition (via `video_id` key)
4. **S3 Storage**: Overlayed videos are stored in S3 for scalable access

## Setup for Scaling

### 1. Create Kafka Topics with Partitions

Run the setup script to create topics with proper partition counts:

```bash
./scripts/setup_kafka_topics.sh
```

Or manually:

```bash
# Create video-frames topic with 6 partitions
kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic video-frames \
  --partitions 6 --replication-factor 1

# Create fire-detections topic with 6 partitions
kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic fire-detections \
  --partitions 6 --replication-factor 1
```

### 2. Configure Environment Variables

Update your `.env` file:

```env
# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_VIDEO_TOPIC_PARTITIONS=6
KAFKA_DETECTIONS_TOPIC_PARTITIONS=6

# S3 Configuration (required for scaling)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
S3_BUCKET=your-bucket-name
S3_DELETE_LOCAL_AFTER_UPLOAD=true  # Delete local files after S3 upload
```

### 3. Run Multiple Stream Processors

Each stream processor instance will automatically consume from different partitions:

```bash
# Terminal 1
python3 streams/fire_detection_stream.py

# Terminal 2
python3 streams/fire_detection_stream.py

# Terminal 3
python3 streams/fire_detection_stream.py

# ... up to N instances (where N = number of partitions)
```

All instances use the same consumer group (`fire-detection-stream`), so Kafka automatically distributes partitions among them.

### 4. Run Multiple S3 Upload Consumers

Each S3 upload consumer instance will automatically consume from different partitions:

```bash
# Terminal 1
python3 consumer/s3_video_consumer.py

# Terminal 2
python3 consumer/s3_video_consumer.py

# Terminal 3
python3 consumer/s3_video_consumer.py

# ... up to M instances (where M = number of video-completions partitions)
```

All instances use the same consumer group (`s3-video-uploader-group`), so Kafka automatically distributes partitions among them.

### 5. Run Multiple Producers

You can run multiple producers simultaneously to process different videos:

```bash
# Terminal 1
python3 producer/video_producer.py video1.mp4 video1

# Terminal 2
python3 producer/video_producer.py video2.mp4 video2

# Terminal 3
python3 producer/video_producer.py video3.mp4 video3
```

## Performance Targets

- **Throughput**: 20-30 frames per second per stream processor
- **With 6 partitions**: Up to 120-180 frames per second total
- **S3 Upload**: Can scale independently with multiple upload consumers
- **Latency**: < 1 second from frame production to video completion event

## How Partitioning Works

### Producer Side

- Producer uses `video_id` as the Kafka message key
- Kafka hashes the key to determine partition
- **All frames from the same video go to the same partition**
- This ensures video frames are processed in order

### Consumer Side

- Multiple consumers with the same `group_id` share partitions
- Each consumer processes 1 or more partitions
- Kafka automatically rebalances partitions when consumers join/leave

### Example

With 6 partitions and 3 consumers:
- Consumer 1: Partitions 0, 1
- Consumer 2: Partitions 2, 3
- Consumer 3: Partitions 4, 5

## Monitoring Scaling

### Check Consumer Lag

```bash
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group fire-detection-stream --describe
```

Look for:
- **LAG**: Number of messages behind
- **CURRENT-OFFSET**: Last processed offset
- **LOG-END-OFFSET**: Latest available offset

### Check Topic Partitions

```bash
kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --topic video-frames
```

## S3 Storage

### Video Organization

Videos are stored in S3 with the following structure:

```
s3://your-bucket/videos/
  ├── video1_with_heatmaps.mp4
  ├── video2_with_heatmaps.mp4
  └── video3_with_heatmaps.mp4
```

### Accessing Videos

Videos can be accessed directly from S3:

```python
import boto3

s3 = boto3.client('s3')
s3.download_file('your-bucket', 'videos/video1_with_heatmaps.mp4', 'local_video.mp4')
```

Or via presigned URLs:

```python
url = s3.generate_presigned_url(
    'get_object',
    Params={'Bucket': 'your-bucket', 'Key': 'videos/video1_with_heatmaps.mp4'},
    ExpiresIn=3600
)
```

## Best Practices

1. **Partition Count**: Set partitions to 2-3x your expected consumer count
2. **Consumer Count**: Don't exceed partition count (extra consumers will be idle)
3. **S3 Bucket**: Use a dedicated bucket for video storage
4. **Monitoring**: Monitor consumer lag to detect bottlenecks
5. **Error Handling**: Ensure consumers handle errors gracefully to avoid blocking partitions

## Troubleshooting

### Consumers Not Scaling

- Check that all consumers use the same `group_id`
- Verify topics have multiple partitions
- Check consumer logs for rebalancing messages

### Uneven Partition Distribution

- Ensure `video_id` keys are well-distributed
- Consider using a hash function if video IDs are sequential

### High Consumer Lag

- Add more consumers (up to partition count)
- Check if consumers are processing slowly (CPU/GPU bound)
- Consider increasing `max_poll_records` in consumer config

### S3 Upload Failures

- Verify AWS credentials and permissions
- Check S3 bucket exists and is accessible
- Monitor S3 request rate limits

