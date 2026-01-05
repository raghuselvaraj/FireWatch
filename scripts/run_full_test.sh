#!/bin/bash
# Complete test script that runs all components and processes test videos

echo "=========================================="
echo "FireWatch Complete Pipeline Test"
echo "=========================================="

# Check if Kafka is running
if ! nc -z localhost 9092 2>/dev/null; then
    echo "⚠️  Kafka doesn't appear to be running on localhost:9092"
    echo "Starting Kafka with Docker Compose..."
    docker-compose up -d
    echo "Waiting for Kafka to be ready..."
    sleep 10
fi

# Create topics if they don't exist
echo ""
echo "Setting up Kafka topics..."
./scripts/setup_kafka_topics.sh

# Check if topics were created
if [ $? -ne 0 ]; then
    echo "⚠️  Warning: Topic creation may have failed. Continuing anyway..."
fi

echo ""
echo "=========================================="
echo "Starting Fire Detection Stream"
echo "=========================================="
echo ""

# Create logs directory
mkdir -p logs

# Start fire detection stream in background
echo "Starting fire detection stream processor..."
python3 streams/fire_detection_stream.py > logs/stream.log 2>&1 &
STREAM_PID=$!
echo "  Stream PID: $STREAM_PID"
echo "  Log file: logs/stream.log"
echo ""

# Wait for stream to initialize
echo "Waiting for stream to initialize..."
sleep 3

# Check if stream is running
if ! kill -0 $STREAM_PID 2>/dev/null; then
    echo "❌ ERROR: Stream processor failed to start!"
    echo "Check logs/stream.log for errors"
    exit 1
fi

echo "✓ Stream processor is running"
echo ""

echo "=========================================="
echo "Processing Test Videos (Sending to Kafka)"
echo "=========================================="
echo ""

# Run the producer to send videos to Kafka
python3 scripts/test_with_videos.py

echo ""
echo "✓ All videos sent to Kafka"
echo ""

echo "=========================================="
echo "Stream Processing Status"
echo "=========================================="
echo ""
echo "📊 Monitoring stream processor logs..."
echo "   (Stream will automatically stop when all messages are processed)"
echo ""

# Function to check if video topic is empty
check_topic_empty() {
    python3 -c "
import sys
sys.path.insert(0, '.')
from kafka import KafkaConsumer
import config

try:
    consumer = KafkaConsumer(
        config.KAFKA_VIDEO_TOPIC,
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        group_id='status-checker',
        consumer_timeout_ms=2000
    )
    
    # Try to get a message
    msg = next(consumer, None)
    consumer.close()
    
    if msg is None:
        print('EMPTY')
    else:
        print('HAS_MESSAGES')
except Exception as e:
    print('ERROR')
" 2>/dev/null
}

# Tail the stream log and monitor for completion
TAIL_PID=""
if [ -f "logs/stream.log" ]; then
    tail -f logs/stream.log &
    TAIL_PID=$!
fi

# Monitor until stream is done
MAX_WAIT=600  # 10 minutes max
WAIT_START=$(date +%s)
LAST_LINE=""

while kill -0 $STREAM_PID 2>/dev/null; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - WAIT_START))
    
    # Check timeout
    if [ $ELAPSED -gt $MAX_WAIT ]; then
        echo ""
        echo "⚠️  Maximum wait time reached ($MAX_WAIT seconds)"
        break
    fi
    
    # Check if video topic is empty (all messages processed)
    TOPIC_STATUS=$(check_topic_empty)
    if [ "$TOPIC_STATUS" = "EMPTY" ]; then
        # Give stream a few more seconds to finish writing video
        echo ""
        echo "✓ All messages processed from video topic"
        echo "  Waiting for stream to finalize videos..."
        sleep 5
        break
    fi
    
    # Show progress every 10 seconds
    if [ $((ELAPSED % 10)) -eq 0 ] && [ $ELAPSED -gt 0 ]; then
        echo -n "⏳ Processing... (${ELAPSED}s elapsed)     \r"
    fi
    
    sleep 1
done

# Stop tailing
if [ -n "$TAIL_PID" ]; then
    kill $TAIL_PID 2>/dev/null
fi

# Wait a moment for stream to finish
sleep 2

# Check if stream is still running
if kill -0 $STREAM_PID 2>/dev/null; then
    echo ""
    echo "Stopping stream processor..."
    kill $STREAM_PID 2>/dev/null
    sleep 2
fi

echo ""
echo "=========================================="
echo "Processing Complete"
echo "=========================================="
echo ""

# Show final stream log summary
if [ -f "logs/stream.log" ]; then
    echo "📊 Final Stream Summary:"
    echo ""
    grep -E "(Video Complete|READY TO WATCH|Summary|fires detected)" logs/stream.log | tail -20
    echo ""
fi

# Show completed videos
echo "📹 Completed Videos:"
CLIPS_DIR="${CLIP_STORAGE_PATH:-clips}"
if [ -d "$CLIPS_DIR" ]; then
    echo ""
    for video_file in "$CLIPS_DIR"/*_with_heatmaps.mp4; do
        if [ -f "$video_file" ]; then
            video_name=$(basename "$video_file")
            video_size=$(du -h "$video_file" | cut -f1)
            echo "  ✅ $video_name ($video_size)"
        fi
    done
    echo ""
    echo "  Location: $CLIPS_DIR"
else
    echo "  (No videos found in $CLIPS_DIR)"
fi

echo ""
echo "=========================================="
echo "Test Complete!"
echo "=========================================="
echo ""
