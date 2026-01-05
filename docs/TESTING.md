# Testing Guide

## Quick Start Testing

### Option 1: Automated Full Test (Recommended)

Run the complete test script that starts all components and processes your test videos:

```bash
./scripts/run_full_test.sh
```

This script will:
1. Start Kafka (if not running)
2. Create Kafka topics
3. Start the fire detection stream
4. Start the S3 upload consumer (if configured)
5. Process all videos in `test_files/` directory
6. Show you how to monitor and stop components

### Option 2: Manual Step-by-Step Testing

#### 1. Start Kafka

```bash
docker-compose up -d
```

Verify Kafka is running:
```bash
docker-compose ps
```

Access Kafka UI at: **http://localhost:8081** (changed from 8080)

#### 2. Create Kafka Topics

```bash
./scripts/setup_kafka_topics.sh
```

#### 3. Start Fire Detection Stream

In Terminal 1:
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

#### 4. Start S3 Upload Consumer (Optional)

In Terminal 2 (if S3 is configured):
```bash
python3 consumer/s3_video_consumer.py
```

#### 5. Process Test Videos

In Terminal 3:
```bash
python3 scripts/test_with_videos.py
```

Or process a specific video:
```bash
python3 producer/video_producer.py test_files/trail_cams/actual_fires/fire_test_1.mp4 fire_test_1
```

## Test Video Structure

Your test videos are organized as:
```
test_files/
├── trail_cams/
│   ├── actual_fires/
│   │   └── fire_test_1.mp4
│   └── no_fires/
│       └── no_fire_test_1.mp4
└── fire_tower_cams/
```

The test script automatically finds and processes all videos in this structure.

## What to Expect

### During Processing

1. **Producer**: Extracts frames and sends to Kafka
   - You'll see: "Frame X sent to topic..."

2. **Stream Processor**: Runs ML inference
   - You'll see: "Processing frame X from video..."
   - If fire detected: "🔥 Fire detected! Probability: X.XX"

3. **S3 Upload Consumer**: Uploads completed videos to S3
   - You'll see: "Inserted detection for video X, frame Y"

### After Processing

1. **Check Clips Directory**:
   ```bash
   ls -lh clips/
   ```
   You should see `.mp4` files for each fire detection

2. **Check S3 bucket** (if configured):
   ```bash
   # List uploaded videos
   aws s3 ls s3://your-bucket-name/videos/
   
   # Or check local clips directory
   ls -lh clips/
   ```

3. **Check Kafka Topics**:
   - Use Kafka UI: http://localhost:8081
   - Or use kafka-console-consumer:
     ```bash
     docker exec -it firewatch-kafka-1 kafka-console-consumer \
       --bootstrap-server localhost:9092 \
       --topic fire-detections \
       --from-beginning
     ```

## Troubleshooting

### "Cannot connect to Kafka"
- Ensure Kafka is running: `docker-compose ps`
- Check `KAFKA_BOOTSTRAP_SERVERS` in `.env`
- Try: `docker-compose restart kafka`

### "No detections found"
- Check if videos actually contain fire
- Lower `CONFIDENCE_THRESHOLD` in `.env` (try 0.15)
- Check stream processor logs for errors

### "Model not loading"
- Setup model first: `python3 scripts/install_fire_detect_nn.py`
- Check internet connection (for Hugging Face download)

### "Clips not being created"
- Check `clips/` directory permissions
- Verify `CLIP_STORAGE_PATH` in `.env`
- Check disk space

### "S3 connection failed"
- Verify credentials in `.env`
- Check network connectivity
- Consumer will fail if S3 not configured (check your .env file)

## Monitoring

### View Logs

If using the automated script:
```bash
tail -f logs/stream.log
tail -f logs/consumer.log
```

### Kafka UI

Access at: **http://localhost:8081**

Features:
- View topics and messages
- Monitor consumer groups
- Check message content

### Check Processing Status

```bash
# Count messages in video-frames topic
docker exec -it firewatch-kafka-1 kafka-run-class \
  kafka.tools.GetOffsetShell \
  --broker-list localhost:9092 \
  --topic video-frames

# Count messages in fire-detections topic
docker exec -it firewatch-kafka-1 kafka-run-class \
  kafka.tools.GetOffsetShell \
  --broker-list localhost:9092 \
  --topic fire-detections
```

## Expected Results

### With Fire Videos
- Fire detections should appear in stream processor
- Clips should be created in `clips/` directory
- Videos should be uploaded to S3 with fire detections

### With No-Fire Videos
- No fire detections (or very few false positives)
- No clips created (unless false positive)
- Videos in S3 with no fire detections

## Next Steps

After successful testing:
1. Review detection accuracy
2. Tune `CONFIDENCE_THRESHOLD` if needed
3. Check video quality and heatmap overlays
4. Verify S3 uploads (if configured)
5. Test with production videos
6. See [docs/LOCAL_TESTING.md](LOCAL_TESTING.md) for local testing guide
