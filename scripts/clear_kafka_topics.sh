#!/bin/bash
# Script to clear all data from FireWatch Kafka topics by deleting and recreating them

KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}

echo "=========================================="
echo "Clearing FireWatch Kafka Topics"
echo "=========================================="
echo ""
echo "⚠️  WARNING: This will delete ALL data from:"
echo "   - video-frames"
echo "   - fire-detections"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Deleting topics..."

# Try docker-compose first
if docker-compose ps kafka 2>/dev/null | grep -q "Up"; then
    echo "Using docker-compose..."
    
    # Delete topics
    docker-compose exec -T kafka /usr/bin/kafka-topics --delete \
      --topic video-frames \
      --bootstrap-server localhost:9092 2>/dev/null || echo "Topic video-frames may not exist"
    
    docker-compose exec -T kafka /usr/bin/kafka-topics --delete \
      --topic fire-detections \
      --bootstrap-server localhost:9092 2>/dev/null || echo "Topic fire-detections may not exist"
    
    # Wait a moment for deletion to complete
    sleep 2
    
    # Recreate topics
    echo ""
    echo "Recreating topics..."
    docker-compose exec -T kafka /usr/bin/kafka-topics --create \
      --topic video-frames \
      --bootstrap-server localhost:9092 \
      --partitions 3 \
      --replication-factor 1 \
      --if-not-exists
    
    docker-compose exec -T kafka /usr/bin/kafka-topics --create \
      --topic fire-detections \
      --bootstrap-server localhost:9092 \
      --partitions 3 \
      --replication-factor 1 \
      --if-not-exists
    
    echo ""
    echo "✓ Topics cleared and recreated successfully!"
    echo ""
    echo "Listing topics:"
    docker-compose exec -T kafka /usr/bin/kafka-topics --list --bootstrap-server localhost:9092

else
    # Try direct docker
    KAFKA_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'kafka' | grep -v 'kafka-ui' | head -1)
    
    if [ -n "$KAFKA_CONTAINER" ]; then
        echo "Using Docker container: $KAFKA_CONTAINER"
        
        docker exec $KAFKA_CONTAINER /usr/bin/kafka-topics --delete \
          --topic video-frames \
          --bootstrap-server localhost:9092 2>/dev/null || echo "Topic video-frames may not exist"
        
        docker exec $KAFKA_CONTAINER /usr/bin/kafka-topics --delete \
          --topic fire-detections \
          --bootstrap-server localhost:9092 2>/dev/null || echo "Topic fire-detections may not exist"
        
        sleep 2
        
        echo ""
        echo "Recreating topics..."
        docker exec $KAFKA_CONTAINER /usr/bin/kafka-topics --create \
          --topic video-frames \
          --bootstrap-server localhost:9092 \
          --partitions 3 \
          --replication-factor 1 \
          --if-not-exists
        
        docker exec $KAFKA_CONTAINER /usr/bin/kafka-topics --create \
          --topic fire-detections \
          --bootstrap-server localhost:9092 \
          --partitions 3 \
          --replication-factor 1 \
          --if-not-exists
        
        echo ""
        echo "✓ Topics cleared and recreated successfully!"
    else
        echo "✗ Error: Could not find Kafka container"
        echo "Please ensure Kafka is running: docker-compose up -d"
        exit 1
    fi
fi

echo ""
echo "=========================================="
echo "Done! All topic data has been cleared."
echo "=========================================="

