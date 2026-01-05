"""
Kafka consumer that uploads completed overlayed videos to S3.

This consumer processes video completion events from the fire detection stream
and uploads the local video files to S3. This separation allows:
- Independent scaling of video processing vs S3 uploads
- Better fault isolation (S3 upload failures don't affect ML processing)
- Multiple upload consumers can process uploads in parallel
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from kafka import KafkaConsumer
from kafka.errors import KafkaError
import boto3
from botocore.exceptions import ClientError

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent))

import config


class S3VideoUploader:
    """Handles uploading videos to S3."""
    
    def __init__(self):
        """Initialize S3 client."""
        if not all([config.S3_BUCKET, config.AWS_ACCESS_KEY_ID, config.AWS_SECRET_ACCESS_KEY]):
            raise ValueError(
                "S3 configuration incomplete. Set S3_BUCKET, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY in .env"
            )
        
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
                region_name=config.AWS_REGION
            )
            # Verify bucket exists
            self.s3_client.head_bucket(Bucket=config.S3_BUCKET)
            print(f"✅ S3 client initialized for bucket: {config.S3_BUCKET}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                raise ValueError(f"S3 bucket '{config.S3_BUCKET}' does not exist")
            else:
                raise ValueError(f"Error connecting to S3: {e}")
        except Exception as e:
            raise ValueError(f"Error initializing S3 client: {e}")
    
    def upload_video(self, local_filepath: str, video_id: str) -> Optional[str]:
        """
        Upload video file to S3.
        
        Args:
            local_filepath: Path to local video file
            video_id: Unique video identifier
            
        Returns:
            S3 path if successful, None otherwise
        """
        if not os.path.exists(local_filepath):
            print(f"⚠️  Video file not found: {local_filepath}")
            return None
        
        try:
            s3_key = f"videos/{video_id}_with_heatmaps.mp4"
            
            # Upload with progress callback
            file_size = os.path.getsize(local_filepath)
            print(f"📤 Uploading {file_size / (1024*1024):.2f} MB to S3...")
            
            self.s3_client.upload_file(
                local_filepath,
                config.S3_BUCKET,
                s3_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
            
            s3_path = f"s3://{config.S3_BUCKET}/{s3_key}"
            print(f"✅ Uploaded to S3: {s3_path}")
            
            # Optionally delete local file after successful upload
            if config.S3_DELETE_LOCAL_AFTER_UPLOAD:
                try:
                    os.remove(local_filepath)
                    print(f"🗑️  Removed local file: {local_filepath}")
                except Exception as e:
                    print(f"⚠️  Could not remove local file: {e}")
            
            return s3_path
            
        except ClientError as e:
            print(f"⚠️  Error uploading video to S3: {e}")
            return None
        except Exception as e:
            print(f"⚠️  Unexpected error uploading to S3: {e}")
            import traceback
            traceback.print_exc()
            return None


class S3VideoConsumer:
    """Kafka consumer that uploads completed videos to S3."""
    
    def __init__(self):
        """Initialize consumer and S3 uploader."""
        self.consumer = KafkaConsumer(
            config.KAFKA_VIDEO_COMPLETIONS_TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            key_deserializer=lambda k: k.decode('utf-8') if k else None,
            group_id="s3-video-uploader-group",  # Multiple consumers can share partitions
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            max_poll_records=10  # Process videos in batches
        )
        
        self.s3_uploader = S3VideoUploader()
        self.upload_count = 0
        self.error_count = 0
    
    def process_message(self, message_value: Dict[str, Any]):
        """Process a video completion message and upload to S3."""
        try:
            video_id = message_value.get("video_id")
            local_filepath = message_value.get("local_filepath")
            stats = message_value.get("stats", {})
            video_metadata = message_value.get("video_metadata", {})
            
            if not video_id or not local_filepath:
                print(f"⚠️  Invalid message: missing video_id or local_filepath")
                self.error_count += 1
                return
            
            print(f"\n{'='*60}")
            print(f"📹 Processing video completion: {video_id}")
            print(f"{'='*60}")
            print(f"  Local file: {local_filepath}")
            print(f"  Stats: {stats}")
            print(f"  Metadata: {video_metadata}")
            
            # Upload to S3
            s3_path = self.s3_uploader.upload_video(local_filepath, video_id)
            
            if s3_path:
                self.upload_count += 1
                print(f"  ✅ S3 path: {s3_path}")
            else:
                self.error_count += 1
                print(f"  ❌ Upload failed")
            
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"Error processing message: {e}")
            import traceback
            traceback.print_exc()
            self.error_count += 1
    
    def run(self):
        """Run the S3 upload consumer."""
        print("Starting S3 Video Upload Consumer...")
        print(f"Consuming from topic: {config.KAFKA_VIDEO_COMPLETIONS_TOPIC}")
        print(f"S3 bucket: {config.S3_BUCKET}")
        print(f"Delete local after upload: {config.S3_DELETE_LOCAL_AFTER_UPLOAD}")
        print(f"Waiting for video completion events... (Press Ctrl+C to stop)\n")
        
        try:
            for message in self.consumer:
                video_id = message.key
                completion_event = message.value
                
                self.process_message(completion_event)
        
        except KeyboardInterrupt:
            print("\n⚠️  Shutting down S3 upload consumer...")
        except Exception as e:
            print(f"Error in S3 upload consumer: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.consumer.close()
            print(f"\n📊 Final stats:")
            print(f"  Successful uploads: {self.upload_count}")
            print(f"  Errors: {self.error_count}")
            print("S3 upload consumer closed")


if __name__ == '__main__':
    try:
        consumer = S3VideoConsumer()
        consumer.run()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\nPlease configure S3 in your .env file:")
        print("  AWS_ACCESS_KEY_ID=your_key")
        print("  AWS_SECRET_ACCESS_KEY=your_secret")
        print("  AWS_REGION=us-east-1")
        print("  S3_BUCKET=your-bucket-name")
        sys.exit(1)

