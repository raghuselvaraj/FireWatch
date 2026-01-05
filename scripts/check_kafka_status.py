"""
Check Kafka topic status and message counts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka import KafkaConsumer, KafkaProducer
import config


def check_topic_status(topic_name: str):
    """Check if topic exists and get message count estimate."""
    try:
        from kafka import TopicPartition
        
        # Create a consumer to check topic
        consumer = KafkaConsumer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            consumer_timeout_ms=2000
        )
        
        # Subscribe to topic
        consumer.subscribe([topic_name])
        
        # Poll to get partition assignment
        consumer.poll(timeout_ms=2000)
        
        partitions = consumer.assignment()
        if not partitions:
            print(f"⚠️  Topic '{topic_name}' may not exist or be empty")
            consumer.close()
            return
        
        print(f"Topic: {topic_name}")
        print(f"Partitions: {len(partitions)}")
        
        # Get end offsets (total messages)
        try:
            end_offsets = consumer.end_offsets(partitions)
            
            total_messages = 0
            for tp, offset in end_offsets.items():
                print(f"  Partition {tp.partition}: {offset} messages")
                total_messages += offset
            
            print(f"Total messages: {total_messages}")
            
        except Exception as e:
            print(f"  Could not get message count: {e}")
            print(f"  Partitions found: {[p.partition for p in partitions]}")
        
        consumer.close()
        
    except Exception as e:
        print(f"Error checking topic '{topic_name}': {e}")


def main():
    print("="*60)
    print("Kafka Topic Status Check")
    print("="*60)
    print(f"Bootstrap servers: {config.KAFKA_BOOTSTRAP_SERVERS}\n")
    
    # Check connection
    try:
        producer = KafkaProducer(bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS, request_timeout_ms=5000)
        producer.close()
        print("✓ Kafka connection successful\n")
    except Exception as e:
        print(f"✗ Cannot connect to Kafka: {e}")
        print("Please ensure Kafka is running: docker-compose up -d")
        return
    
    # Check topics
    print("Checking topics...\n")
    check_topic_status(config.KAFKA_VIDEO_TOPIC)
    print()
    check_topic_status(config.KAFKA_DETECTIONS_TOPIC)
    
    print("\n" + "="*60)
    print("Diagnostics:")
    print("="*60)
    print("If video-frames has messages but fire-detections is empty:")
    print("  → Stream processor may not be running")
    print("  → Or stream processor stopped before processing")
    print("\nIf both topics are empty:")
    print("  → No videos have been processed yet")
    print("  → Run: python3 producer/video_producer.py <video_file> <video_id>")


if __name__ == "__main__":
    main()

