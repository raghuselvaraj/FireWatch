#!/bin/bash
# Complete test script that runs all components and processes test videos

# Parse command line arguments
VIDEO_ARG=""
STREAM_INSTANCES=1  # Default to 1 instance
FAST_TESTS=false    # Default to running all tests

while [[ $# -gt 0 ]]; do
    case $1 in
        --instances|-i)
            STREAM_INSTANCES="$2"
            shift 2
            ;;
        --fast-tests|-f)
            FAST_TESTS=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--instances N] [--fast-tests] [video_file]"
            echo ""
            echo "Options:"
            echo "  --instances, -i N    Number of stream processor instances to run (default: 1)"
            echo "                       Each instance processes a subset of Kafka partitions"
            echo "                       Recommended: 1-6 (matches number of partitions)"
            echo "  --fast-tests, -f     Run only fast unit tests (skips slow/integration tests)"
            echo "                       Default: runs all tests"
            echo ""
            echo "Arguments:"
            echo "  video_file           Optional path to a specific video file to process"
            echo ""
            exit 0
            ;;
        *)
            if [ -z "$VIDEO_ARG" ]; then
                VIDEO_ARG="$1"
            else
                echo "⚠️  Unknown argument: $1"
                echo "Use --help for usage information"
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate instances count
if ! [[ "$STREAM_INSTANCES" =~ ^[1-9][0-9]*$ ]]; then
    echo "❌ ERROR: --instances must be a positive integer (got: $STREAM_INSTANCES)"
    exit 1
fi

echo "=========================================="
echo "FireWatch Complete Pipeline Test"
echo "=========================================="
if [ -n "$VIDEO_ARG" ]; then
    echo "Video: $VIDEO_ARG"
fi
echo "Stream instances: $STREAM_INSTANCES"

# Run unit tests first
echo ""
echo "=========================================="
echo "Running Unit Tests"
echo "=========================================="
echo ""

# Check if pytest is available
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "⚠️  Warning: pytest not found. Skipping unit tests."
    echo "   Install with: pip3 install pytest"
    echo ""
else
    if [ "$FAST_TESTS" = true ]; then
        echo "Running fast unit tests (skipping slow/integration tests)..."
        # Run only the fastest, most critical unit tests
        # Override pytest.ini to remove coverage options that cause issues
        python3 -m pytest tests/test_utils.py tests/test_video_producer.py \
            -v --tb=short \
            --override-ini="addopts=-v --strict-markers --tb=short" 2>&1
        
        # Check if tests passed
        TEST_EXIT_CODE=$?
        if [ $TEST_EXIT_CODE -ne 0 ]; then
            echo ""
            echo "❌ Fast unit tests failed! Exiting..."
            echo "   Fix the failing tests before running the pipeline test"
            echo ""
            exit $TEST_EXIT_CODE
        else
            echo ""
            echo "✓ Fast unit tests passed"
            echo ""
        fi
    else
        echo "Running all unit tests..."
        # Run all tests - override pytest.ini to remove coverage options that cause issues
        python3 -m pytest tests/ \
            -v --tb=short \
            --override-ini="addopts=-v --strict-markers --tb=short" 2>&1
        
        # Check if tests passed
        TEST_EXIT_CODE=$?
        if [ $TEST_EXIT_CODE -ne 0 ]; then
            echo ""
            echo "❌ Unit tests failed! Exiting..."
            echo "   Fix the failing tests before running the pipeline test"
            echo ""
            exit $TEST_EXIT_CODE
        else
            echo ""
            echo "✓ All unit tests passed"
            echo ""
        fi
    fi
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

# Kill any existing stream processor instances from previous runs
echo "Cleaning up any existing stream processor instances..."
pkill -f "fire_detection_stream.py" 2>/dev/null && sleep 2 || true
pkill -f "test_with_videos.py" 2>/dev/null && sleep 1 || true
pkill -f "s3_video_consumer.py" 2>/dev/null && sleep 1 || true
echo "  ✓ Cleanup complete"

# Clean up progress file from previous runs
PROGRESS_FILE="/tmp/firewatch_video_progress.json"
if [ -f "$PROGRESS_FILE" ]; then
    rm -f "$PROGRESS_FILE"
    echo "  ✓ Removed old progress file"
fi

# Create timestamped output directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="clips/${TIMESTAMP}"
mkdir -p "$OUTPUT_DIR"
echo "📁 Output directory: $OUTPUT_DIR"
echo ""

# Create logs directory
mkdir -p logs

# Start fire detection stream processors in background with timestamped output directory
# Use unique consumer group ID to avoid offset issues from previous test runs
# All instances use the same consumer group ID so Kafka partitions are shared
echo "1. Starting fire detection stream processor(s)..."
export KAFKA_GROUP_ID="fire-detection-stream-test-${TIMESTAMP}"

# Array to store all stream PIDs
STREAM_PIDS=()

# Start multiple instances
for i in $(seq 1 $STREAM_INSTANCES); do
    if [ $STREAM_INSTANCES -eq 1 ]; then
        LOG_FILE="logs/stream.log"
    else
        LOG_FILE="logs/stream_${i}.log"
    fi
    
    echo "   Starting instance $i/$STREAM_INSTANCES..."
    CLIP_STORAGE_PATH="$OUTPUT_DIR" KAFKA_GROUP_ID="$KAFKA_GROUP_ID" python3 streams/fire_detection_stream.py > "$LOG_FILE" 2>&1 &
    INSTANCE_PID=$!
    STREAM_PIDS+=($INSTANCE_PID)
    echo "   Instance $i PID: $INSTANCE_PID"
    echo "   Instance $i log: $LOG_FILE"
done

# Wait for streams to initialize
sleep 3

# Check if all streams are running
ALL_RUNNING=true
for i in "${!STREAM_PIDS[@]}"; do
    PID=${STREAM_PIDS[$i]}
    INSTANCE_NUM=$((i + 1))
    if ! kill -0 $PID 2>/dev/null; then
        echo "❌ ERROR: Stream processor instance $INSTANCE_NUM failed to start!"
        if [ $STREAM_INSTANCES -eq 1 ]; then
            echo "Check logs/stream.log for errors"
        else
            echo "Check logs/stream_${INSTANCE_NUM}.log for errors"
        fi
        ALL_RUNNING=false
    fi
done

if [ "$ALL_RUNNING" = false ]; then
    # Kill any running instances
    for PID in "${STREAM_PIDS[@]}"; do
        kill -TERM $PID 2>/dev/null || true
    done
    exit 1
fi

echo "   ✓ All $STREAM_INSTANCES stream processor instance(s) are running"
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
PROGRESS_FILE="/tmp/firewatch_video_progress.json"
echo "3. Starting video producer (processing videos and sending frames to Kafka)..."
# If using multiple stream instances, process multiple videos to utilize all instances
# Otherwise, process single video (or specified video)
if [ "$STREAM_INSTANCES" -gt 1 ] && [ -z "$VIDEO_ARG" ]; then
    # Multiple instances but no specific video - process multiple videos in parallel
    echo "   Processing multiple videos in parallel (to utilize $STREAM_INSTANCES stream instances)..."
    PROGRESS_FILE="$PROGRESS_FILE" STREAM_INSTANCES="$STREAM_INSTANCES" python3 scripts/test_with_videos.py > logs/producer.log 2>&1 &
elif [ -n "$VIDEO_ARG" ]; then
    # Specific video provided - process just that one
    echo "   Processing single video: $VIDEO_ARG"
    PROGRESS_FILE="$PROGRESS_FILE" python3 scripts/test_with_videos.py "$VIDEO_ARG" > logs/producer.log 2>&1 &
else
    # Single instance, no specific video - process default
    PROGRESS_FILE="$PROGRESS_FILE" python3 scripts/test_with_videos.py > logs/producer.log 2>&1 &
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
        # Print per-video progress bars (Producer + Stream for each video)
        if [ -f "$PROGRESS_FILE" ]; then
            # Read video progress from file and update stream progress from Kafka
            VIDEO_COUNT=$(python3 -c "import json; d=json.load(open('$PROGRESS_FILE')); print(len(d.get('videos', [])))" 2>/dev/null || echo "0")
            if [ "$VIDEO_COUNT" -gt 0 ]; then
                # Move cursor up to clear previous video progress bars (2 lines per video: producer + stream)
                printf "\033[%dA" "$((VIDEO_COUNT * 2))"
                
                # Print progress bars for each video (Producer + Stream)
                # Both producer_progress and stream_progress are written to the file by their respective processes
                PROGRESS_FILE="$PROGRESS_FILE" python3 << 'PYTHON_EOF'
import json
import sys
import os

try:
    # Read progress file (both producer and stream write to this file)
    progress_file = os.environ.get('PROGRESS_FILE', '/tmp/firewatch_video_progress.json')
    with open(progress_file) as f:
        data = json.load(f)
    
    # Display each video with Producer and Stream bars
    # Producer writes producer_progress, stream processor writes stream_progress
    for video in data.get('videos', []):
        name = video['name'][:32]
        producer_prog = video.get('producer_progress', 0)
        stream_prog = video.get('stream_progress', 0)  # Read from file (updated by stream processor)
        
        # CRITICAL: Stream can NEVER exceed producer progress (can't process more than sent)
        # Cap stream progress at producer progress
        if stream_prog > producer_prog:
            stream_prog = producer_prog
        
        # Create bars
        bar_length = 25
        prod_filled = int((producer_prog * bar_length) / 100)
        prod_bar = '█' * prod_filled + '░' * (bar_length - prod_filled)
        
        stream_filled = int((stream_prog * bar_length) / 100)
        stream_bar = '█' * stream_filled + '░' * (bar_length - stream_filled)
        
        # Print Producer bar (use newline, not carriage return, since we're printing multiple videos)
        print(f'📤 {name:<32} Producer: [{prod_bar}] {producer_prog:3d}%')
        # Print Stream bar
        print(f'📥 {name:<32} Stream:   [{stream_bar}] {stream_prog:3d}%')
except Exception as e:
    # Fallback: just show producer progress
    try:
        progress_file = os.environ.get('PROGRESS_FILE', '/tmp/firewatch_video_progress.json')
        with open(progress_file) as f:
            data = json.load(f)
        for video in data.get('videos', []):
            name = video['name'][:32]
            producer_prog = video.get('producer_progress', 0)
            stream_prog = video.get('stream_progress', 0)
            bar_length = 25
            prod_filled = int((producer_prog * bar_length) / 100)
            prod_bar = '█' * prod_filled + '░' * (bar_length - prod_filled)
            stream_filled = int((stream_prog * bar_length) / 100)
            stream_bar = '█' * stream_filled + '░' * (bar_length - stream_filled)
            print(f'📤 {name:<32} Producer: [{prod_bar}] {producer_prog:3d}%')
            print(f'📥 {name:<32} Stream:   [{stream_bar}] {stream_prog:3d}%')
    except:
        pass
PYTHON_EOF
                
                # Move cursor back down
                printf "\033[%dB" "$((VIDEO_COUNT * 2))"
            fi
        fi
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

# Stop all stream processor instances
if [ ${#STREAM_PIDS[@]} -gt 0 ]; then
    echo "  Stopping stream processor instance(s)..."
    for i in "${!STREAM_PIDS[@]}"; do
        PID=${STREAM_PIDS[$i]}
        INSTANCE_NUM=$((i + 1))
        if kill -0 $PID 2>/dev/null; then
            echo "    Stopping instance $INSTANCE_NUM (PID: $PID)..."
            kill -TERM $PID 2>/dev/null
        fi
    done
    
    # Wait for all instances to stop gracefully
    for i in {1..10}; do
        ALL_STOPPED=true
        for PID in "${STREAM_PIDS[@]}"; do
            if kill -0 $PID 2>/dev/null; then
                ALL_STOPPED=false
                break
            fi
        done
        if [ "$ALL_STOPPED" = true ]; then
            break
        fi
        sleep 1
    done
    
    # Force kill any remaining instances
    for i in "${!STREAM_PIDS[@]}"; do
        PID=${STREAM_PIDS[$i]}
        if kill -0 $PID 2>/dev/null; then
            INSTANCE_NUM=$((i + 1))
            echo "    Force killing instance $INSTANCE_NUM (PID: $PID)..."
            kill -KILL $PID 2>/dev/null
        fi
    done
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

# Show final stream log summary (from all instances)
echo "📊 Final Stream Summary:"
echo ""
if [ $STREAM_INSTANCES -eq 1 ]; then
    if [ -f "logs/stream.log" ]; then
        grep -E 'Video Complete|READY TO WATCH|Summary|fires detected' logs/stream.log 2>/dev/null | tail -20 || true
    fi
else
    # Show summary from all instances
    for i in $(seq 1 $STREAM_INSTANCES); do
        LOG_FILE="logs/stream_${i}.log"
        if [ -f "$LOG_FILE" ]; then
            echo "Instance $i:"
            grep -E 'Video Complete|READY TO WATCH|Summary|fires detected' "$LOG_FILE" 2>/dev/null | tail -10 || true
            echo ""
        fi
    done
fi
echo ""

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

# Clean up all temporary files
echo "Cleaning up temporary files..."
if [ -f "$PROGRESS_FILE" ]; then
    rm -f "$PROGRESS_FILE"
    echo "  ✓ Removed progress file: $PROGRESS_FILE"
fi

# Clean up test codec file if it exists
if [ -f "/tmp/test_codec_firewatch.mp4" ]; then
    rm -f "/tmp/test_codec_firewatch.mp4"
    echo "  ✓ Removed test codec file: /tmp/test_codec_firewatch.mp4"
fi

echo "  ✓ Cleanup complete"

echo ""
echo "=========================================="
echo "Test Complete!"
echo "=========================================="
echo ""
