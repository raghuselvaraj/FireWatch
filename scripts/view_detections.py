"""
View fire detection results from Kafka.

This script consumes detection messages from Kafka and displays them
in a readable format, perfect for verifying ML processing.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka import KafkaConsumer
import config


def format_detection(detection: dict) -> str:
    """Format a detection message for display."""
    video_id = detection.get("video_id", "unknown")
    frame_num = detection.get("frame_number", "?")
    timestamp = detection.get("timestamp", "?")
    has_fire = detection.get("has_fire", False)
    probability = detection.get("fire_probability", 0.0)
    detections = detection.get("detections", [])
    clip_path = detection.get("clip_path")
    
    # Build output
    output = []
    output.append(f"\n{'='*70}")
    output.append(f"Video: {video_id} | Frame: {frame_num} | Time: {timestamp}")
    output.append(f"{'='*70}")
    
    if has_fire:
        output.append(f"🔥 FIRE DETECTED! (Confidence: {probability:.2%})")
        output.append(f"\nDetections ({len(detections)}):")
        for i, det in enumerate(detections, 1):
            bbox = det.get("bbox", [])
            conf = det.get("confidence", 0.0)
            cls = det.get("class", "unknown")
            output.append(f"  {i}. Class: {cls} | Confidence: {conf:.2%} | BBox: {bbox}")
        
        if clip_path:
            output.append(f"\n📹 Video clip saved: {clip_path}")
    else:
        output.append(f"✓ No fire detected (probability: {probability:.2%})")
    
    output.append(f"{'='*70}\n")
    
    return "\n".join(output)


def view_detections(from_beginning: bool = True, limit: int = None):
    """Consume and display detection messages from Kafka."""
    import time
    from kafka import TopicPartition
    
    print("="*70)
    print("FireWatch Detection Viewer")
    print("="*70)
    print(f"Consuming from topic: {config.KAFKA_DETECTIONS_TOPIC}")
    print(f"Bootstrap servers: {config.KAFKA_BOOTSTRAP_SERVERS}")
    
    # Use a unique consumer group to avoid offset conflicts
    import uuid
    group_id = f"detection-viewer-{uuid.uuid4().hex[:8]}"
    
    consumer = KafkaConsumer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        key_deserializer=lambda k: k.decode('utf-8') if k else None,
        group_id=group_id,
        auto_offset_reset='earliest',
        enable_auto_commit=False,  # Don't commit offsets so we can re-read
        consumer_timeout_ms=5000  # Wait 5 seconds for messages
    )
    
    # Subscribe to topic
    consumer.subscribe([config.KAFKA_DETECTIONS_TOPIC])
    
    # Wait for partition assignment
    print("Waiting for partition assignment...")
    consumer.poll(timeout_ms=2000)
    
    # Get partitions and set offsets
    partitions = consumer.assignment()
    if partitions:
        print(f"Found {len(partitions)} partition(s)")
        if from_beginning:
            # Seek to beginning of all partitions
            consumer.seek_to_beginning(*partitions)
            for partition in partitions:
                print(f"  Partition {partition.partition}: reading from beginning")
        else:
            # Seek to end (only new messages)
            consumer.seek_to_end(*partitions)
            for partition in partitions:
                print(f"  Partition {partition.partition}: reading new messages only")
    else:
        print("⚠️  No partitions found. Topic may not exist or be empty.")
        print("   Waiting a moment for partition assignment...")
        time.sleep(2)
        partitions = consumer.assignment()
        if not partitions:
            print("   Still no partitions. Topic may be empty or not exist.")
            consumer.close()
            return
        if from_beginning:
            consumer.seek_to_beginning(*partitions)
        else:
            consumer.seek_to_end(*partitions)
    
    print("Press Ctrl+C to stop\n")
    
    try:
        message_count = 0
        fire_count = 0
        
        for message in consumer:
            message_count += 1
            detection = message.value
            
            # Display the detection
            print(format_detection(detection))
            
            if detection.get("has_fire", False):
                fire_count += 1
            
            # Check limit
            if limit and message_count >= limit:
                print(f"\nReached limit of {limit} messages.")
                break
        
        if message_count == 0:
            print("\n⚠️  No messages found in topic.")
            print("\nPossible reasons:")
            print("  1. The fire detection stream is not running")
            print("  2. No videos have been processed yet")
            print("  3. Messages were already consumed by another consumer")
            print("\nTo process videos, run:")
            print("  python3 scripts/test_with_videos.py")
            print("  OR")
            print("  python3 producer/video_producer.py <video_file> <video_id>")
        else:
            print(f"\n{'='*70}")
            print(f"Summary: {message_count} messages processed, {fire_count} fires detected")
            print(f"{'='*70}")
    
    except KeyboardInterrupt:
        print("\n\nStopped viewing detections.")
    finally:
        consumer.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="View fire detection results from Kafka")
    parser.add_argument("-n", "--new-only", action="store_true",
                       help="Only show new messages (don't read from beginning)")
    parser.add_argument("-l", "--limit", type=int, default=None,
                       help="Limit number of messages to display")
    
    args = parser.parse_args()
    view_detections(from_beginning=not args.new_only, limit=args.limit)

