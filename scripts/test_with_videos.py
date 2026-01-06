"""
Test script to process test videos through the FireWatch pipeline.

This script processes all videos in the test_files directory and sends them
through the pipeline for fire detection.

Usage:
    python3 scripts/test_with_videos.py [video_path]
    
    If video_path is provided, only that video will be processed.
    If not provided, processes all videos in test_files/ directory.
"""
import os
import sys
import time
import subprocess
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from producer.video_producer import VideoProducer
import config


def find_test_videos(base_path: str = "test_files", video_name: str = None) -> list:
    """Find all video files in the test_files directory, or a specific video if specified."""
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.flv']
    videos = []
    
    base = Path(base_path)
    if not base.exists():
        print(f"Test files directory not found: {base_path}")
        return videos
    
    # If specific video name is provided, only find that video
    if video_name:
        # Try exact match first (with and without extension)
        for ext in video_extensions:
            # Exact filename match
            exact_match = base.rglob(f"{video_name}{ext}")
            videos.extend(exact_match)
            # Pattern match as fallback
            pattern_match = base.rglob(f"*{video_name}*{ext}")
            videos.extend(pattern_match)
        # Remove duplicates while preserving order
        seen = set()
        unique_videos = []
        for v in videos:
            if v not in seen:
                seen.add(v)
                unique_videos.append(v)
        if unique_videos:
            return sorted(unique_videos)
        else:
            print(f"⚠️  Video '{video_name}' not found, searching for all videos...")
    
    # Otherwise find all videos
    for ext in video_extensions:
        videos.extend(base.rglob(f"*{ext}"))
    
    return sorted(videos)


def test_video(video_path: Path, video_id: str = None):
    """Process a single test video."""
    if not video_id:
        # Generate video ID from filename
        video_id = f"test_{video_path.stem}"
    
    print(f"\n{'='*60}")
    print(f"Processing: {video_path.name}")
    print(f"Video ID: {video_id}")
    print(f"Path: {video_path}")
    print(f"{'='*60}")
    
    producer = VideoProducer()
    try:
        producer.process_video_file(str(video_path), video_id)
        print(f"✓ Successfully processed {video_path.name}")
        return True
    except Exception as e:
        print(f"✗ Error processing {video_path.name}: {e}")
        return False
    finally:
        producer.close()


def main():
    """Main test function."""
    print("="*60)
    print("FireWatch Pipeline Test - Video Processing")
    print("="*60)
    
    # Check Kafka connection
    print("\n1. Checking Kafka connection...")
    try:
        from kafka import KafkaProducer
        test_prod = KafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            request_timeout_ms=5000
        )
        test_prod.close()
        print(f"✓ Kafka connection successful: {config.KAFKA_BOOTSTRAP_SERVERS}")
    except Exception as e:
        print(f"✗ Cannot connect to Kafka: {e}")
        print("\nPlease ensure Kafka is running:")
        print("  docker-compose up -d")
        print("  OR")
        print("  Start Kafka manually and check KAFKA_BOOTSTRAP_SERVERS in .env")
        sys.exit(1)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Process videos through FireWatch pipeline')
    parser.add_argument('video', nargs='?', help='Path to a specific video file to process (optional)')
    args = parser.parse_args()
    
    # Find test videos
    print("\n2. Finding test videos...")
    videos = []
    
    if args.video:
        # User provided a specific video path
        video_path = Path(args.video)
        if video_path.exists() and video_path.is_file():
            print(f"   Processing specified video: {video_path}")
            videos = [video_path]
        else:
            print(f"✗ Video file not found: {video_path}")
            sys.exit(1)
    else:
        # Default to fire-short-3 for testing if no argument provided
        video_name = os.getenv("TEST_VIDEO_NAME", "fire-short-3")
        print(f"   Looking for video: {video_name}")
        videos = find_test_videos(video_name=video_name)
        
        if not videos:
            print("✗ No test videos found in test_files/ directory")
            print("\nExpected structure:")
            print("  test_files/")
            print("    trail_cams/")
            print("      actual_fires/")
            print("        fire_test_1.mp4")
            print("      no_fires/")
            print("        no_fire_test_1.mp4")
            print("\nOr provide a video path as an argument:")
            print("  python3 scripts/test_with_videos.py /path/to/video.mp4")
            sys.exit(1)
    
    print(f"✓ Found {len(videos)} test video(s)")
    for video in videos:
        print(f"  - {video}")
    
    # Process videos
    print(f"\n3. Processing {len(videos)} video(s)...")
    print("   (Frames will be processed in real-time as they're published)")
    
    results = []
    for i, video in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] Processing {video.name}...")
        try:
            success = test_video(video)
            results.append((video.name, success))
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
            results.append((video.name, False))
        
        # Small delay between videos
        if i < len(videos):
            time.sleep(2)
    
    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")
    successful = sum(1 for _, success in results if success)
    print(f"Processed: {successful}/{len(results)} videos successfully")
    
    for video_name, success in results:
        status = "✓" if success else "✗"
        print(f"  {status} {video_name}")
    
    print(f"\n{'='*60}")
    print("Next Steps:")
    print("1. Check the fire detection stream terminal for detection results")
    print("2. Check the consumer terminal for S3 upload confirmations")
    print("3. View detection results:")
    print("   SELECT * FROM fire_detections WHERE has_fire = TRUE;")
    print("4. Check the clips/ directory for extracted video clips")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
