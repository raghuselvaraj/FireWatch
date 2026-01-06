#!/bin/bash
# Complete test script that runs all components and processes test videos

# Parse command line arguments
VIDEO_ARG=""
if [ $# -gt 0 ]; then
    VIDEO_ARG="$1"
fi

echo "=========================================="
echo "FireWatch Complete Pipeline Test"
echo "=========================================="
if [ -n "$VIDEO_ARG" ]; then
    echo "Video: $VIDEO_ARG"
fi

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

# Flush Kafka topics and reset offsets for clean test run
echo ""
echo "Flushing Kafka topics and resetting offsets..."
flush_kafka_topics() {
    # Find Kafka container - try multiple methods
    KAFKA_CONTAINER=""
    
    # Method 1: Use docker-compose exec (works with service name)
    if docker-compose ps kafka 2>/dev/null | grep -q "Up"; then
        # Try to use docker-compose exec directly (preferred method)
        USE_DOCKER_COMPOSE=true
    else
        USE_DOCKER_COMPOSE=false
        # Method 2: Find by name pattern
        KAFKA_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'kafka' | grep -v 'kafka-ui' | head -1)
    fi
    
    if [ "$USE_DOCKER_COMPOSE" = false ] && [ -z "$KAFKA_CONTAINER" ]; then
        echo "  ⚠️  Kafka container not found, skipping topic flush"
        return
    fi
    
    if [ "$USE_DOCKER_COMPOSE" = true ]; then
        echo "  Using docker-compose to access Kafka service"
        EXEC_CMD="docker-compose exec -T kafka"
    else
        echo "  Using Kafka container: $KAFKA_CONTAINER"
        EXEC_CMD="docker exec $KAFKA_CONTAINER"
    fi
    
    # Delete topics to clear all messages
    echo "  Deleting topics..."
    $EXEC_CMD /usr/bin/kafka-topics --delete \
      --topic video-frames \
      --bootstrap-server localhost:9092 2>/dev/null || true
    
    $EXEC_CMD /usr/bin/kafka-topics --delete \
      --topic fire-detections \
      --bootstrap-server localhost:9092 2>/dev/null || true
    
    $EXEC_CMD /usr/bin/kafka-topics --delete \
      --topic video-completions \
      --bootstrap-server localhost:9092 2>/dev/null || true
    
    # Wait for deletion to complete
    sleep 2
    
    # Recreate topics
    echo "  Recreating topics..."
    $EXEC_CMD /usr/bin/kafka-topics --create \
      --topic video-frames \
      --bootstrap-server localhost:9092 \
      --partitions 3 \
      --replication-factor 1 \
      --if-not-exists 2>/dev/null || true
    
    $EXEC_CMD /usr/bin/kafka-topics --create \
      --topic fire-detections \
      --bootstrap-server localhost:9092 \
      --partitions 3 \
      --replication-factor 1 \
      --if-not-exists 2>/dev/null || true
    
    $EXEC_CMD /usr/bin/kafka-topics --create \
      --topic video-completions \
      --bootstrap-server localhost:9092 \
      --partitions 3 \
      --replication-factor 1 \
      --if-not-exists 2>/dev/null || true
    
    # Reset all consumer group offsets (in case any groups exist)
    echo "  Resetting consumer group offsets..."
    for group in fire-detection-stream firewatch-consumer-group; do
        for topic in video-frames fire-detections video-completions; do
            $EXEC_CMD /usr/bin/kafka-consumer-groups \
              --bootstrap-server localhost:9092 \
              --group "$group" \
              --reset-offsets \
              --to-earliest \
              --topic "$topic" \
              --execute 2>/dev/null || true
        done
    done
    
    echo "  ✓ Topics flushed and offsets reset"
}

flush_kafka_topics

echo ""
echo "=========================================="
echo "Starting All Components (Simultaneous)"
echo "=========================================="
echo ""

# Create timestamped output directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="clips/${TIMESTAMP}"
mkdir -p "$OUTPUT_DIR"
echo "📁 Output directory: $OUTPUT_DIR"
echo ""

# Create logs directory
mkdir -p logs

# Start fire detection stream in background with timestamped output directory
# Use unique consumer group ID to avoid offset issues from previous test runs
echo "1. Starting fire detection stream processor..."
export KAFKA_GROUP_ID="fire-detection-stream-test-${TIMESTAMP}"
CLIP_STORAGE_PATH="$OUTPUT_DIR" KAFKA_GROUP_ID="$KAFKA_GROUP_ID" python3 streams/fire_detection_stream.py > logs/stream.log 2>&1 &
STREAM_PID=$!
echo "   Stream PID: $STREAM_PID"
echo "   Log file: logs/stream.log"

# Wait for stream to initialize
sleep 3

# Check if stream is running
if ! kill -0 $STREAM_PID 2>/dev/null; then
    echo "❌ ERROR: Stream processor failed to start!"
    echo "Check logs/stream.log for errors"
    exit 1
fi

echo "   ✓ Stream processor is running"
echo ""

# Start S3 upload consumer in background (if S3 is configured)
echo "2. Starting S3 upload consumer..."
CONSUMER_PID=""
if python3 -c "import config; assert config.S3_BUCKET and config.AWS_ACCESS_KEY_ID" 2>/dev/null; then
    CLIP_STORAGE_PATH="$OUTPUT_DIR" python3 consumer/s3_video_consumer.py > logs/consumer.log 2>&1 &
    CONSUMER_PID=$!
    echo "   Consumer PID: $CONSUMER_PID"
    echo "   Log file: logs/consumer.log"
    sleep 2
    if kill -0 $CONSUMER_PID 2>/dev/null; then
        echo "   ✓ S3 upload consumer is running"
    else
        echo "   ⚠️  S3 upload consumer failed to start (check logs/consumer.log)"
        CONSUMER_PID=""
    fi
else
    echo "   ⚠️  S3 not configured - skipping S3 upload consumer"
    echo "   (Set S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY to enable)"
fi
echo ""

# Start video producer in background (processes videos and sends frames to Kafka)
echo "3. Starting video producer (processing videos and sending frames to Kafka)..."
if [ -n "$VIDEO_ARG" ]; then
    python3 scripts/test_with_videos.py "$VIDEO_ARG" > logs/producer.log 2>&1 &
else
    python3 scripts/test_with_videos.py > logs/producer.log 2>&1 &
fi
PRODUCER_PID=$!
echo "   Producer PID: $PRODUCER_PID"
echo "   Log file: logs/producer.log"
echo ""

echo "=========================================="
echo "All Components Running Simultaneously"
echo "=========================================="
echo ""
echo "📊 Processing pipeline:"
echo "   Producer → Kafka → Stream Processor → Kafka → S3 Consumer → S3"
echo ""
echo "   Frames are processed in real-time as they're published!"
echo ""

echo "=========================================="
echo "Monitoring Pipeline (Real-time Processing)"
echo "=========================================="
echo ""
echo "📊 All components running simultaneously..."
echo "   Producer: Sending frames to Kafka"
echo "   Stream: Processing frames in real-time"
if [ -n "$CONSUMER_PID" ]; then
    echo "   Consumer: Uploading videos to S3"
fi
echo ""

# Function to check if video topic is empty
# This checks if there are uncommitted messages for the current consumer group
# Function to get Kafka topic lag and total messages for progress calculation
get_topic_stats() {
    python3 -c "
import sys
sys.path.insert(0, '.')
from kafka import KafkaConsumer, KafkaAdminClient
from kafka.admin import ConfigResource, ConfigResourceType
import config
import time
import os

try:
    # Get the consumer group ID from environment (set by test script)
    group_id = os.environ.get('KAFKA_GROUP_ID', 'fire-detection-stream-test-default')
    
    # Use admin client to check consumer group lag (doesn't interfere with active consumer)
    admin = KafkaAdminClient(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        client_id='lag-checker'
    )
    
    # Create a temporary consumer to get partition info (different group ID to avoid interference)
    temp_consumer = KafkaConsumer(
        config.KAFKA_VIDEO_TOPIC,
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        group_id='temp-lag-checker-' + str(int(time.time())),  # Unique group ID
        auto_offset_reset='earliest',
        consumer_timeout_ms=2000,
        enable_auto_commit=False
    )
    
    # Get all partitions for the topic
    partitions = temp_consumer.partitions_for_topic(config.KAFKA_VIDEO_TOPIC)
    temp_consumer.close()
    
    if not partitions:
        print('HAS_MESSAGES:0:0')  # Can't determine, assume there are messages
        admin.close()
        exit(0)
    
    # Check consumer group lag using admin client (non-intrusive)
    from kafka import KafkaConsumer
    # Use a separate consumer to check the actual consumer group's position
    check_consumer = KafkaConsumer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=False,
        consumer_timeout_ms=1000
    )
    
    total_lag = 0
    total_messages = 0
    for partition_id in partitions:
        from kafka import TopicPartition
        partition = TopicPartition(config.KAFKA_VIDEO_TOPIC, partition_id)
        
        # Get end offset (total messages in partition)
        end_offsets = check_consumer.end_offsets([partition])
        end_offset = end_offsets.get(partition, 0)
        total_messages += end_offset
        
        # Get committed offset for the consumer group
        try:
            committed = check_consumer.committed(partition)
            committed_offset = committed if committed is not None else 0
            lag = end_offset - committed_offset
            total_lag += lag
        except:
            # If we can't get committed offset, assume there's lag
            total_lag += 1000
    
    check_consumer.close()
    admin.close()
    
    # Return status:lag:total format
    if total_lag < 50:
        print(f'EMPTY:{total_lag}:{total_messages}')
    else:
        print(f'HAS_MESSAGES:{total_lag}:{total_messages}')
except Exception as e:
    # On error, assume there are messages (safer to wait longer)
    print('HAS_MESSAGES:0:0')
" 2>/dev/null
}

check_topic_empty() {
    # Extract just the status from get_topic_stats
    STATS=$(get_topic_stats)
    echo "$STATS" | cut -d: -f1
}

# Monitor all processes
MAX_WAIT=1200  # 20 minutes max (for long videos)
WAIT_START=$(date +%s)
PRODUCER_DONE=false
PRODUCER_FINISH_TIME=""
MAX_TOTAL_MSGS=0  # Track maximum messages seen (for producer progress calculation)
LOCKED_TOTAL_MSGS=0  # Locked denominator once producer finishes (prevents progress from going backwards)
MAX_PROCESSED=0  # Track maximum processed messages seen (prevents progress bar from going backwards)
MAX_STREAM_PROGRESS=0  # Track maximum progress percentage seen (NEVER let progress decrease)
PRODUCER_ELAPSED=""  # Track producer elapsed time (printed after stream finishes)

echo "⏳ Waiting for producer to finish sending all frames..."
while true; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - WAIT_START))
    
    # Check timeout
    if [ $ELAPSED -gt $MAX_WAIT ]; then
        echo ""
        echo "⚠️  Maximum wait time reached ($MAX_WAIT seconds)"
        break
    fi
    
    # Check if producer is done (silently track, don't print anything)
    if ! kill -0 $PRODUCER_PID 2>/dev/null; then
        if [ "$PRODUCER_DONE" = false ]; then
            # Calculate producer elapsed time (store for later, don't print now)
            PRODUCER_ELAPSED=$ELAPSED
            PRODUCER_DONE=true
        fi
    fi
    
    # Check if video topic is empty (all messages processed by stream)
    # Wait longer after producer finishes to ensure all messages are processed
    if [ "$PRODUCER_DONE" = true ]; then
        # Wait at least 90 seconds after producer finishes before checking
        # This gives more time for the stream processor to catch up
        if [ $((ELAPSED - PRODUCER_FINISH_TIME)) -gt 90 ]; then
            TOPIC_STATUS=$(check_topic_empty)
            # Also get stats for logging
            STATS=$(get_topic_stats)
            LAG=$(echo "$STATS" | cut -d: -f2)
            TOTAL_MSGS=$(echo "$STATS" | cut -d: -f3)
            if [ "$TOPIC_STATUS" = "EMPTY" ]; then
                # Print newline first to clear the progress bar line
                echo ""
                echo "✓ All frames processed by stream processor"
                # Print producer elapsed time now (after stream finishes)
                if [ -n "$PRODUCER_ELAPSED" ]; then
                    PROD_MINUTES=$((PRODUCER_ELAPSED / 60))
                    PROD_SECONDS=$((PRODUCER_ELAPSED % 60))
                    echo "✓ Producer finished sending all frames (${PROD_MINUTES}m ${PROD_SECONDS}s)"
                fi
                echo "  Waiting for stream to finalize videos..."
                sleep 10  # Give extra time for video finalization
                break
            fi
        fi
    fi
    
    # Track when producer finished
    if [ "$PRODUCER_DONE" = true ] && [ -z "$PRODUCER_FINISH_TIME" ]; then
        PRODUCER_FINISH_TIME=$ELAPSED
    fi
    
    # Update progress bars every second (overwrites same line)
    # Only update if we're still in the loop (not breaking out)
    # Skip if we just detected completion (to avoid printing on same line as completion message)
    SKIP_PROGRESS_BAR=false
    if [ "$PRODUCER_DONE" = true ] && [ $((ELAPSED - PRODUCER_FINISH_TIME)) -gt 90 ]; then
        # Check if topic is empty - if so, we're about to print completion message
        TOPIC_CHECK=$(check_topic_empty)
        if [ "$TOPIC_CHECK" = "EMPTY" ]; then
            SKIP_PROGRESS_BAR=true
        fi
    fi
    
    if [ $ELAPSED -gt 0 ] && [ "$SKIP_PROGRESS_BAR" = false ]; then
        # Calculate progress based on actual data, not elapsed time
        # Get Kafka topic stats (lag and total messages)
        STATS=$(get_topic_stats)
        STATUS=$(echo "$STATS" | cut -d: -f1)
        LAG=$(echo "$STATS" | cut -d: -f2)
        TOTAL_MSGS=$(echo "$STATS" | cut -d: -f3)
        
        # Create progress bar (40 characters for each bar)
        BAR_LENGTH=40
        
        # Track maximum total messages seen
        if [ -n "$TOTAL_MSGS" ] && [ "$TOTAL_MSGS" -gt "$MAX_TOTAL_MSGS" ]; then
            MAX_TOTAL_MSGS=$TOTAL_MSGS
        fi
        
        # Lock the denominator once producer finishes (prevents progress from going backwards)
        if [ "$PRODUCER_DONE" = true ] && [ "$LOCKED_TOTAL_MSGS" -eq 0 ]; then
            # Use MAX_TOTAL_MSGS as the final count (or current if max wasn't tracked properly)
            if [ "$MAX_TOTAL_MSGS" -gt 0 ]; then
                LOCKED_TOTAL_MSGS=$MAX_TOTAL_MSGS
            else
                LOCKED_TOTAL_MSGS=$TOTAL_MSGS
            fi
        fi
        
        # Producer progress bar - based on actual messages in topic
        if [ "$PRODUCER_DONE" = false ]; then
            # Producer still running - use TOTAL_MSGS as progress indicator
            # Since we don't know final count, use a logarithmic scale that increases smoothly
            # but caps at 90% until producer finishes
            if [ -n "$TOTAL_MSGS" ] && [ "$TOTAL_MSGS" -gt 0 ]; then
                # Use a simple formula: progress = min(90, log_scale(TOTAL_MSGS))
                # For smooth increase: progress = min(90, (TOTAL_MSGS / (TOTAL_MSGS + 500)) * 90)
                # This gives: 0 messages = 0%, 100 messages = ~15%, 500 messages = ~45%, 2000 messages = ~78%, etc.
                PRODUCER_PROGRESS=$((TOTAL_MSGS * 90 / (TOTAL_MSGS + 500)))
                if [ $PRODUCER_PROGRESS -gt 90 ]; then
                    PRODUCER_PROGRESS=90
                fi
                if [ $PRODUCER_PROGRESS -lt 1 ] && [ "$TOTAL_MSGS" -gt 0 ]; then
                    PRODUCER_PROGRESS=1
                fi
            else
                # Can't get stats - use time-based fallback
                PRODUCER_PROGRESS=$((ELAPSED * 100 / MAX_WAIT))
                if [ $PRODUCER_PROGRESS -gt 90 ]; then
                    PRODUCER_PROGRESS=90
                fi
            fi
        else
            PRODUCER_PROGRESS=100
        fi
        
        # Stream progress bar - based on actual messages processed (monotonically increasing)
        # CRITICAL: Progress bars should NEVER go backwards - track maximum processed count
        if [ -n "$TOTAL_MSGS" ] && [ "$TOTAL_MSGS" -gt 0 ]; then
            # Calculate current processed messages (total - lag)
            PROCESSED=$((TOTAL_MSGS - LAG))
            if [ $PROCESSED -lt 0 ]; then
                PROCESSED=0
            fi
            
            # Track maximum processed count seen (prevents progress from going backwards)
            # This handles cases where lag increases faster than new messages arrive
            if [ $PROCESSED -gt $MAX_PROCESSED ]; then
                MAX_PROCESSED=$PROCESSED
            fi
            
            # Use locked total as denominator if producer finished, otherwise use max seen
            # This prevents the denominator from changing and causing progress to go backwards
            if [ "$LOCKED_TOTAL_MSGS" -gt 0 ]; then
                # Producer finished - use locked total (stable denominator)
                DENOMINATOR=$LOCKED_TOTAL_MSGS
            elif [ "$MAX_TOTAL_MSGS" -gt 0 ]; then
                # Producer still running - use max seen so far (may still increase, but better than current)
                DENOMINATOR=$MAX_TOTAL_MSGS
            else
                # Fallback: use current total (will fluctuate, but better than nothing)
                DENOMINATOR=$TOTAL_MSGS
            fi
            
            # Calculate progress using maximum processed count (never decreases)
            # This ensures progress bar only moves forward, never backwards
            if [ "$DENOMINATOR" -gt 0 ]; then
                CALCULATED_PROGRESS=$((MAX_PROCESSED * 100 / DENOMINATOR))
            else
                CALCULATED_PROGRESS=0
            fi
            
            # Cap at 100% and ensure non-negative
            if [ $CALCULATED_PROGRESS -gt 100 ]; then
                CALCULATED_PROGRESS=100
            fi
            if [ $CALCULATED_PROGRESS -lt 0 ]; then
                CALCULATED_PROGRESS=0
            fi
            
            # CRITICAL: Never let progress decrease - use maximum progress seen
            # This handles edge cases where denominator changes or calculations fluctuate
            if [ $CALCULATED_PROGRESS -gt $MAX_STREAM_PROGRESS ]; then
                MAX_STREAM_PROGRESS=$CALCULATED_PROGRESS
            fi
            STREAM_PROGRESS=$MAX_STREAM_PROGRESS
        else
            # Can't get stats - use time-based estimate (only as fallback)
            STREAM_PROGRESS=$((ELAPSED * 100 / MAX_WAIT / 3))
            if [ $STREAM_PROGRESS -gt 100 ]; then
                STREAM_PROGRESS=100
            fi
        fi
        
        # Calculate filled/empty for producer bar
        PRODUCER_FILLED=$((PRODUCER_PROGRESS * BAR_LENGTH / 100))
        if [ $PRODUCER_FILLED -gt $BAR_LENGTH ]; then
            PRODUCER_FILLED=$BAR_LENGTH
        fi
        PRODUCER_EMPTY=$((BAR_LENGTH - PRODUCER_FILLED))
        
        # Build producer bar string
        PRODUCER_BAR=""
        if [ $PRODUCER_FILLED -gt 0 ]; then
            for i in $(seq 1 $PRODUCER_FILLED); do
                PRODUCER_BAR="${PRODUCER_BAR}█"
            done
        fi
        if [ $PRODUCER_EMPTY -gt 0 ]; then
            for i in $(seq 1 $PRODUCER_EMPTY); do
                PRODUCER_BAR="${PRODUCER_BAR}░"
            done
        fi
        
        # Calculate filled/empty for stream bar
        STREAM_FILLED=$((STREAM_PROGRESS * BAR_LENGTH / 100))
        if [ $STREAM_FILLED -gt $BAR_LENGTH ]; then
            STREAM_FILLED=$BAR_LENGTH
        fi
        STREAM_EMPTY=$((BAR_LENGTH - STREAM_FILLED))
        
        # Build stream bar string
        STREAM_BAR=""
        if [ $STREAM_FILLED -gt 0 ]; then
            for i in $(seq 1 $STREAM_FILLED); do
                STREAM_BAR="${STREAM_BAR}█"
            done
        fi
        if [ $STREAM_EMPTY -gt 0 ]; then
            for i in $(seq 1 $STREAM_EMPTY); do
                STREAM_BAR="${STREAM_BAR}░"
            done
        fi
        
        # Print both progress bars - always overwrite the same line using \r and \033[K
        printf "\r\033[K📤 Producer: [%s] %d%% | 📥 Stream: [%s] %d%%" "$PRODUCER_BAR" "$PRODUCER_PROGRESS" "$STREAM_BAR" "$STREAM_PROGRESS"
    fi
    
    sleep 1
done

# Print newline after progress bars (move cursor down to clear the progress bar lines)
echo ""
echo ""

# Calculate and display total elapsed time
FINAL_TIME=$(date +%s)
FINAL_ELAPSED=$((FINAL_TIME - WAIT_START))
MINUTES=$((FINAL_ELAPSED / 60))
SECONDS=$((FINAL_ELAPSED % 60))
echo "⏱️  Total processing time: ${MINUTES}m ${SECONDS}s"
echo ""

echo "Waiting for all components to finish..."
sleep 3

# Gracefully stop all processes
echo ""
echo "Stopping all components gracefully..."

# Stop stream processor
if kill -0 $STREAM_PID 2>/dev/null; then
    echo "  Stopping stream processor..."
    kill -TERM $STREAM_PID 2>/dev/null
    for i in {1..10}; do
        if ! kill -0 $STREAM_PID 2>/dev/null; then
            break
        fi
        sleep 1
    done
    if kill -0 $STREAM_PID 2>/dev/null; then
        kill -KILL $STREAM_PID 2>/dev/null
    fi
fi

# Stop S3 consumer
if [ -n "$CONSUMER_PID" ] && kill -0 $CONSUMER_PID 2>/dev/null; then
    echo "  Stopping S3 consumer..."
    kill -TERM $CONSUMER_PID 2>/dev/null
    sleep 2
    if kill -0 $CONSUMER_PID 2>/dev/null; then
        kill -KILL $CONSUMER_PID 2>/dev/null
    fi
fi

# Wait for producer (should already be done)
if kill -0 $PRODUCER_PID 2>/dev/null; then
    echo "  Waiting for producer to finish..."
    wait $PRODUCER_PID 2>/dev/null
fi

sleep 2

echo ""
echo "=========================================="
echo "Processing Complete"
echo "=========================================="
echo ""

# Show final stream log summary
if [ -f "logs/stream.log" ]; then
    echo "📊 Final Stream Summary:"
    echo ""
    grep -E 'Video Complete|READY TO WATCH|Summary|fires detected' logs/stream.log 2>/dev/null | tail -20 || true
    echo ""
fi

# Show completed videos
echo "📹 Completed Videos:"
if [ -n "$OUTPUT_DIR" ] && [ -d "$OUTPUT_DIR" ]; then
    CLIPS_DIR="$OUTPUT_DIR"
else
    CLIPS_DIR="${CLIP_STORAGE_PATH:-clips}"
fi

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
