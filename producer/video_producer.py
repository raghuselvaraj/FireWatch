"""Kafka producer that reads video files and publishes frames to Kafka topic."""
import cv2
import json
import base64
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
from kafka import KafkaProducer
from kafka.errors import KafkaError

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent))

import config


class VideoProducer:
    """Produces video frames to Kafka topic."""
    
    def __init__(self, bootstrap_servers: str = None):
        """Initialize Kafka producer."""
        self.bootstrap_servers = bootstrap_servers or config.KAFKA_BOOTSTRAP_SERVERS
        self.topic = config.KAFKA_VIDEO_TOPIC
        
        self.producer = KafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks=1,  # Only wait for leader acknowledgment (faster, allows true parallel processing)
            retries=3,
            max_in_flight_requests_per_connection=5,  # Allow more in-flight for better throughput
            compression_type='gzip',  # Compress messages for better throughput
            batch_size=16384,  # Batch messages for better throughput
            linger_ms=10  # Wait up to 10ms to batch messages
        )
    
    def encode_frame(self, frame: bytes) -> str:
        """Encode frame as base64 string."""
        return base64.b64encode(frame).decode('utf-8')
    
    def process_video_file(self, video_path: str, video_id: Optional[str] = None):
        """
        Read video file and publish frames to Kafka.
        
        Args:
            video_path: Path to video file
            video_id: Optional unique identifier for the video
        """
        if not video_id:
            video_id = f"video_{int(time.time())}"
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
        
        frame_count = 0
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        # Don't print here - let the test script handle progress display
        # This allows multiple videos to process in parallel without output conflicts
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Extract frames based on interval
                if frame_count % config.FRAME_EXTRACTION_INTERVAL == 0:
                    # Resize frame if needed
                    if config.FRAME_WIDTH and config.FRAME_HEIGHT:
                        frame = cv2.resize(frame, (config.FRAME_WIDTH, config.FRAME_HEIGHT))
                    
                    # Encode frame as JPEG
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    frame_bytes = buffer.tobytes()
                    
                    # Create message
                    message = {
                        "video_id": video_id,
                        "frame_number": frame_count,
                        "timestamp": datetime.utcnow().isoformat(),
                        "fps": fps,
                        "frame_data": self.encode_frame(frame_bytes),
                        "width": frame.shape[1],
                        "height": frame.shape[0]
                    }
                    
                    # Send to Kafka (async for better throughput)
                    # Using video_id as key ensures all frames from same video go to same partition
                    # Don't wait for acknowledgment - fully async for parallel processing
                    self.producer.send(
                        self.topic,
                        key=video_id,
                        value=message
                    )
                
                frame_count += 1
            
            # Wait for all async sends to complete before closing
            # This ensures all frames are actually sent to Kafka
            # Don't print - let test script handle progress
            self.producer.flush(timeout=60)  # Wait up to 60 seconds for all messages
            
        finally:
            cap.release()
    
    def close(self):
        """Close the producer."""
        self.producer.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python video_producer.py <video_file_path> [video_id]")
        sys.exit(1)
    
    video_path = sys.argv[1]
    video_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    producer = VideoProducer()
    try:
        producer.process_video_file(video_path, video_id)
    finally:
        producer.close()
