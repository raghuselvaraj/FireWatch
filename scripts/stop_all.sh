#!/bin/bash
# Script to stop all FireWatch processes and containers

echo "🛑 Stopping all FireWatch processes..."

# Kill stream processor processes
echo "Stopping stream processors..."
pkill -f "fire_detection_stream.py" && echo "  ✓ Stream processors stopped" || echo "  (No stream processors running)"

# Kill producer processes
echo "Stopping video producers..."
pkill -f "test_with_videos.py" && echo "  ✓ Producers stopped" || echo "  (No producers running)"

# Kill consumer processes
echo "Stopping S3 consumers..."
pkill -f "s3_video_consumer.py" && echo "  ✓ Consumers stopped" || echo "  (No consumers running)"

# Stop Kafka if running via docker-compose
if [ -f "docker-compose.yml" ]; then
    echo "Stopping Kafka (docker-compose)..."
    docker-compose down 2>/dev/null && echo "  ✓ Kafka stopped" || echo "  (Kafka not running via docker-compose)"
fi

# Also check for standalone Kafka containers
KAFKA_CONTAINERS=$(docker ps --format "{{.Names}}" | grep -E "kafka|zookeeper" | tr '\n' ' ')
if [ -n "$KAFKA_CONTAINERS" ]; then
    echo "Stopping Kafka containers: $KAFKA_CONTAINERS"
    docker stop $KAFKA_CONTAINERS 2>/dev/null && echo "  ✓ Kafka containers stopped" || echo "  (Could not stop containers)"
fi

# Check for any remaining Python processes
REMAINING=$(ps aux | grep -E "fire_detection_stream|test_with_videos|s3_video_consumer" | grep -v grep | wc -l | tr -d ' ')
if [ "$REMAINING" -gt 0 ]; then
    echo ""
    echo "⚠️  Warning: $REMAINING process(es) still running:"
    ps aux | grep -E "fire_detection_stream|test_with_videos|s3_video_consumer" | grep -v grep
    echo ""
    read -p "Force kill remaining processes? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pkill -9 -f "fire_detection_stream.py"
        pkill -9 -f "test_with_videos.py"
        pkill -9 -f "s3_video_consumer.py"
        echo "  ✓ Force killed all processes"
    fi
else
    echo ""
    echo "✓ All FireWatch processes stopped"
fi

echo ""
echo "Done."

