"""
View raw messages from Kafka topics for debugging.

This script allows you to inspect messages in any Kafka topic.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka import KafkaConsumer
import config


def view_topic_messages(topic_name: str, limit: int = None):
    """View messages from a Kafka topic."""
    print(f"Viewing messages from topic: {topic_name}")
    print(f"Bootstrap servers: {config.KAFKA_BOOTSTRAP_SERVERS}")
    if limit:
        print(f"Limit: {limit} messages")
    print("Press Ctrl+C to stop\n")
    
    consumer = KafkaConsumer(
        topic_name,
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        key_deserializer=lambda k: k.decode('utf-8') if k else None,
        group_id=f"viewer-{topic_name}",
        auto_offset_reset='earliest',
        enable_auto_commit=True,
        consumer_timeout_ms=2000
    )
    
    try:
        count = 0
        for message in consumer:
            count += 1
            print(f"\n{'='*70}")
            print(f"Message #{count}")
            print(f"Key: {message.key}")
            print(f"Partition: {message.partition}")
            print(f"Offset: {message.offset}")
            print(f"Timestamp: {message.timestamp}")
            print(f"\nValue:")
            print(json.dumps(message.value, indent=2))
            print(f"{'='*70}")
            
            if limit and count >= limit:
                break
        
        if count == 0:
            print("No messages found in topic.")
    
    except KeyboardInterrupt:
        print("\n\nStopped viewing messages.")
    finally:
        consumer.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="View Kafka topic messages")
    parser.add_argument("topic", nargs="?", default=config.KAFKA_DETECTIONS_TOPIC,
                       help="Topic name to view (default: fire-detections)")
    parser.add_argument("-l", "--limit", type=int, default=None,
                       help="Limit number of messages to display")
    
    args = parser.parse_args()
    view_topic_messages(args.topic, args.limit)

