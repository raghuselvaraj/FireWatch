#!/bin/bash
# Script to create Kafka topics with proper partitions for horizontal scaling
# This enables processing 20-30 frames per second across multiple consumers

set -e

KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
VIDEO_TOPIC="${KAFKA_VIDEO_TOPIC:-video-frames}"
DETECTIONS_TOPIC="${KAFKA_DETECTIONS_TOPIC:-fire-detections}"
VIDEO_PARTITIONS="${KAFKA_VIDEO_TOPIC_PARTITIONS:-6}"
DETECTIONS_PARTITIONS="${KAFKA_DETECTIONS_TOPIC_PARTITIONS:-6}"
COMPLETIONS_PARTITIONS="${KAFKA_VIDEO_COMPLETIONS_TOPIC_PARTITIONS:-3}"
REPLICATION_FACTOR="${KAFKA_REPLICATION_FACTOR:-1}"

echo "Setting up Kafka topics for horizontal scaling..."
echo "Bootstrap servers: $KAFKA_BOOTSTRAP_SERVERS"
echo ""

# Check if kafka-topics.sh is available
if command -v kafka-topics.sh &> /dev/null; then
    KAFKA_TOPICS_CMD="kafka-topics.sh"
elif [ -f "/usr/local/bin/kafka-topics.sh" ]; then
    KAFKA_TOPICS_CMD="/usr/local/bin/kafka-topics.sh"
elif [ -f "/opt/kafka/bin/kafka-topics.sh" ]; then
    KAFKA_TOPICS_CMD="/opt/kafka/bin/kafka-topics.sh"
else
    echo "Error: kafka-topics.sh not found. Please install Kafka or set KAFKA_HOME."
    exit 1
fi

# Create video-frames topic
echo "Creating topic: $VIDEO_TOPIC with $VIDEO_PARTITIONS partitions..."
$KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
    --create \
    --topic $VIDEO_TOPIC \
    --partitions $VIDEO_PARTITIONS \
    --replication-factor $REPLICATION_FACTOR \
    --if-not-exists || echo "Topic $VIDEO_TOPIC may already exist"

# Create fire-detections topic
echo "Creating topic: $DETECTIONS_TOPIC with $DETECTIONS_PARTITIONS partitions..."
$KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
    --create \
    --topic $DETECTIONS_TOPIC \
    --partitions $DETECTIONS_PARTITIONS \
    --replication-factor $REPLICATION_FACTOR \
    --if-not-exists || echo "Topic $DETECTIONS_TOPIC may already exist"

# Create video-completions topic
COMPLETIONS_TOPIC="${KAFKA_VIDEO_COMPLETIONS_TOPIC:-video-completions}"
echo "Creating topic: $COMPLETIONS_TOPIC with $COMPLETIONS_PARTITIONS partitions..."
$KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
    --create \
    --topic $COMPLETIONS_TOPIC \
    --partitions $COMPLETIONS_PARTITIONS \
    --replication-factor $REPLICATION_FACTOR \
    --if-not-exists || echo "Topic $COMPLETIONS_TOPIC may already exist"

echo ""
echo "✅ Topics created successfully!"
echo ""
echo "Topic configuration:"
$KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --describe --topic $VIDEO_TOPIC
echo ""
$KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --describe --topic $DETECTIONS_TOPIC
echo ""
$KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --describe --topic $COMPLETIONS_TOPIC
echo ""
echo "To scale horizontally:"
echo "  - Run multiple stream processors with the same consumer group_id"
echo "  - Run multiple S3 upload consumers with the same consumer group_id"
echo "  - Each consumer will process different partitions"
echo "  - With $VIDEO_PARTITIONS partitions, you can run up to $VIDEO_PARTITIONS stream processors"
echo "  - With $COMPLETIONS_PARTITIONS partitions, you can run up to $COMPLETIONS_PARTITIONS S3 upload consumers"
