#!/bin/bash
# Alternative: Reset consumer group offsets instead of deleting topics
# This preserves topics but resets where consumers start reading

KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}

echo "=========================================="
echo "Reset Consumer Group Offsets"
echo "=========================================="
echo ""
echo "This will reset consumer offsets to 'earliest' for:"
echo "   - fire-detection-stream"
echo "   - firewatch-consumer-group"
echo "   - detection-viewer-*"
echo ""
echo "Note: This doesn't delete messages, just resets where consumers start reading"
echo ""

if docker-compose ps kafka 2>/dev/null | grep -q "Up"; then
    echo "Resetting offsets..."
    
    # Reset offsets for fire-detection-stream group
    docker-compose exec -T kafka /usr/bin/kafka-consumer-groups --bootstrap-server localhost:9092 \
      --group fire-detection-stream \
      --reset-offsets \
      --to-earliest \
      --topic video-frames \
      --execute 2>/dev/null || echo "Group fire-detection-stream may not exist"
    
    docker-compose exec -T kafka /usr/bin/kafka-consumer-groups --bootstrap-server localhost:9092 \
      --group fire-detection-stream \
      --reset-offsets \
      --to-earliest \
      --topic fire-detections \
      --execute 2>/dev/null || echo "Group fire-detection-stream may not exist"
    
    # Reset offsets for firewatch-consumer-group
    docker-compose exec -T kafka /usr/bin/kafka-consumer-groups --bootstrap-server localhost:9092 \
      --group firewatch-consumer-group \
      --reset-offsets \
      --to-earliest \
      --topic fire-detections \
      --execute 2>/dev/null || echo "Group firewatch-consumer-group may not exist"
    
    echo ""
    echo "✓ Consumer offsets reset!"
    echo ""
    echo "Note: To completely clear data, use: ./scripts/clear_kafka_topics.sh"
    
else
    echo "✗ Error: Kafka not running"
    exit 1
fi

