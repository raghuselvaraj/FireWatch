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
import threading
import json
import fcntl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime

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


def test_video(video_path: Path, video_id: str = None, progress_callback=None, status_dict=None, status_lock=None, progress_file=None):
    """Process a single test video (runs in parallel with other videos)."""
    if not video_id:
        # Generate video ID from filename
        video_id = f"test_{video_path.stem}"
    
    # Get total frame count for progress tracking
    import cv2
    import config
    cap = cv2.VideoCapture(str(video_path))
    if cap.isOpened():
        total_frames_in_video = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # Calculate how many frames will actually be sent (based on extraction interval)
        if total_frames_in_video > 0 and config.FRAME_EXTRACTION_INTERVAL > 0:
            # Only frames at extraction interval will be sent
            total_frames = (total_frames_in_video // config.FRAME_EXTRACTION_INTERVAL) + (1 if total_frames_in_video % config.FRAME_EXTRACTION_INTERVAL > 0 else 0)
        else:
            total_frames = total_frames_in_video
    else:
        total_frames = 0
    cap.release()
    
    # Mark as processing
    if status_dict and status_lock:
        with status_lock:
            if video_id in status_dict:
                status_dict[video_id]["status"] = "processing"
                status_dict[video_id]["start_time"] = time.time()
                status_dict[video_id]["total_frames"] = total_frames
                status_dict[video_id]["frames_sent"] = 0
                status_dict[video_id]["max_producer_progress"] = 0  # Track max progress to prevent going backward
    
    producer = VideoProducer()
    try:
        # Track frames sent for progress
        frames_sent = 0
        import config
        
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_count % config.FRAME_EXTRACTION_INTERVAL == 0:
                # Update progress
                frames_sent += 1
                if status_dict and status_lock and progress_file:
                    with status_lock:
                        if video_id in status_dict:
                            status_dict[video_id]["frames_sent"] = frames_sent
                            # Update progress file with file locking to prevent race conditions
                            # CRITICAL: Multiple producer threads and stream processor all write to this file
                            max_retries = 5
                            retry_delay = 0.1
                            # Calculate progress, ensuring 100% when frames_sent == total_frames
                            if total_frames > 0:
                                producer_prog = min(100, int((frames_sent * 100) / total_frames))
                                # If we've sent all frames, ensure it's exactly 100%
                                if frames_sent >= total_frames:
                                    producer_prog = 100
                            else:
                                producer_prog = 0
                            
                            for attempt in range(max_retries):
                                try:
                                    # Read with shared lock
                                    with open(progress_file, 'r') as f:
                                        fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                                        progress_data = json.load(f)
                                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                                    
                                    # Find existing video to preserve stream_progress
                                    video_found = False
                                    for v in progress_data["videos"]:
                                        if v.get("video_id") == video_id:
                                            # Update producer progress, preserve stream_progress
                                            v["producer_progress"] = producer_prog
                                            v["total_frames"] = total_frames
                                            # CRITICAL: Don't touch stream_progress - stream processor manages it
                                            video_found = True
                                            break
                                    
                                    if not video_found:
                                        progress_data["videos"].append({
                                            "video_id": video_id,
                                            "name": Path(video_path).name,
                                            "producer_progress": producer_prog,
                                            "stream_progress": 0,  # Only set to 0 for NEW videos
                                            "total_frames": total_frames
                                        })
                                    
                                    # Write with exclusive lock
                                    os.makedirs(os.path.dirname(progress_file) if os.path.dirname(progress_file) else '.', exist_ok=True)
                                    with open(progress_file, 'w') as f:
                                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                                        json.dump(progress_data, f)
                                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                                    break
                                except (IOError, OSError, json.JSONDecodeError):
                                    # File locked or invalid - retry
                                    if attempt < max_retries - 1:
                                        time.sleep(retry_delay)
                                        continue
                                    # Last attempt failed - skip this update
                                    break
                
                # Resize if needed
                if config.FRAME_WIDTH and config.FRAME_HEIGHT:
                    frame = cv2.resize(frame, (config.FRAME_WIDTH, config.FRAME_HEIGHT))
                
                # Encode and send
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()
                
                message = {
                    "video_id": video_id,
                    "frame_number": frame_count,
                    "timestamp": datetime.utcnow().isoformat(),
                    "fps": fps,
                    "frame_data": producer.encode_frame(frame_bytes),
                    "width": frame.shape[1],
                    "height": frame.shape[0]
                }
                
                producer.producer.send(
                    config.KAFKA_VIDEO_TOPIC,
                    key=video_id,
                    value=message
                )
            
            frame_count += 1
        
        cap.release()
        producer.producer.flush(timeout=60)
        
        # Final progress update - ensure 100% when all frames are sent
        if status_dict and status_lock and progress_file:
            with status_lock:
                if video_id in status_dict:
                    status_dict[video_id]["frames_sent"] = frames_sent
                    # Final update to ensure 100% progress
                    max_retries = 5
                    retry_delay = 0.1
                    producer_prog = 100  # All frames sent = 100%
                    
                    for attempt in range(max_retries):
                        try:
                            # Read with shared lock
                            with open(progress_file, 'r') as f:
                                fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                                progress_data = json.load(f)
                                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                            
                            # Find existing video and update to 100%
                            for v in progress_data["videos"]:
                                if v.get("video_id") == video_id:
                                    v["producer_progress"] = producer_prog
                                    v["total_frames"] = total_frames
                                    break
                            
                            # Write with exclusive lock
                            os.makedirs(os.path.dirname(progress_file) if os.path.dirname(progress_file) else '.', exist_ok=True)
                            with open(progress_file, 'w') as f:
                                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                                json.dump(progress_data, f)
                                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                            break
                        except (IOError, OSError, json.JSONDecodeError):
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                            break
        
        if progress_callback:
            progress_callback(video_id, True, None)
        return True
    except Exception as e:
        if progress_callback:
            progress_callback(video_id, False, str(e))
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
        # If multiple stream instances are being used, process multiple videos
        # Otherwise, process single default video
        stream_instances = int(os.getenv("STREAM_INSTANCES", "1"))
        if stream_instances > 1:
            # Process multiple videos to utilize all stream instances
            print(f"   Processing multiple videos (to utilize {stream_instances} stream instances)...")
            videos = find_test_videos()  # Find all videos
            # Limit to reasonable number (e.g., 3-6 videos max)
            if len(videos) > stream_instances:
                videos = videos[:stream_instances]
            print(f"   Selected {len(videos)} video(s) for parallel processing")
        else:
            # Single instance - process default video
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
    
    # Process videos IN PARALLEL to enable parallel stream processing
    print(f"\n3. Processing {len(videos)} video(s) in parallel...")
    print("   (All videos will be sent to Kafka simultaneously)")
    print("   (Each video goes to a different partition, enabling parallel processing)")
    print("")  # Empty line before progress bar
    
    results = []
    video_status = {}  # Track status of each video: {video_id: {"name": str, "status": "pending|processing|done|error", "error": str, "start_time": float}}
    max_producer_progress = {}  # Track maximum producer progress per video (prevents progress from going backward)
    completed_count = 0
    total_videos = len(videos)
    
    # Initialize status for all videos
    for video in videos:
        video_id = f"test_{video.stem}"
        video_status[video_id] = {
            "name": video.name,
            "status": "pending",
            "error": None,
            "start_time": None
        }
        max_producer_progress[video_id] = 0  # Initialize max progress tracking
    
    # Thread-safe progress callback
    progress_lock = threading.Lock()
    
    def update_progress(video_id, success, error_msg):
        nonlocal completed_count
        with progress_lock:
            if video_id in video_status:
                if success:
                    video_status[video_id]["status"] = "done"
                else:
                    video_status[video_id]["status"] = "error"
                    video_status[video_id]["error"] = error_msg
                completed_count += 1
    
    # Process all videos in parallel using ThreadPoolExecutor
    # This ensures all videos are sent to Kafka at the same time
    # Each video gets a different video_id, so they hash to different partitions
    # Multiple stream processor instances can then process them in parallel
    with ThreadPoolExecutor(max_workers=len(videos)) as executor:
        # Get progress file path
        progress_file = os.getenv("PROGRESS_FILE", "/tmp/firewatch_video_progress.json")
        
        # Initialize progress file with all videos
        try:
            initial_data = {
                "videos": [
                    {
                        "video_id": f"test_{video.stem}",
                        "name": video.name,
                        "producer_progress": 0,
                        "stream_progress": 0
                    }
                    for video in videos
                ]
            }
            with open(progress_file, 'w') as f:
                json.dump(initial_data, f)
        except:
            pass
        
        # Submit all videos for parallel processing
        future_to_video = {
            executor.submit(test_video, video, None, update_progress, video_status, progress_lock, progress_file): video 
            for video in videos
        }
        
        # Show individual progress bars for each video
        start_time = time.time()
        last_update = 0
        
        while completed_count < total_videos:
            current_time = time.time()
            
            # Check if any futures are done and collect results
            for future in list(future_to_video.keys()):
                if future.done():
                    video = future_to_video.pop(future)
                    try:
                        success = future.result()
                        results.append((video.name, success))
                    except Exception as e:
                        results.append((video.name, False))
                        video_id = f"test_{video.stem}"
                        if video_id in video_status:
                            with progress_lock:
                                video_status[video_id]["status"] = "error"
                                video_status[video_id]["error"] = str(e)
                                completed_count += 1
            
            # Update progress bars every 0.3 seconds (only if not all done)
            if current_time - last_update >= 0.3 and completed_count < total_videos:
                # Write progress to file for run_full_test.sh to read
                progress_file = os.getenv("PROGRESS_FILE", "/tmp/firewatch_video_progress.json")
                with progress_lock:
                    # CRITICAL: Read existing progress file first to preserve stream_progress!
                    # The stream processor writes stream_progress, we must not overwrite it
                    max_retries = 5
                    retry_delay = 0.1
                    progress_data = {"videos": []}
                    
                    # Read with file locking (or create if doesn't exist)
                    if os.path.exists(progress_file):
                        for attempt in range(max_retries):
                            try:
                                with open(progress_file, 'r') as f:
                                    fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                                    progress_data = json.load(f)
                                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                                break
                            except (IOError, OSError, json.JSONDecodeError):
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                    continue
                                progress_data = {"videos": []}
                    
                    # Create a map of existing videos by video_id to preserve stream_progress
                    existing_videos = {v.get("video_id"): v for v in progress_data.get("videos", [])}
                    
                    # Clear and rebuild videos list, preserving stream_progress
                    progress_data["videos"] = []
                    for video_id, status_info in sorted(video_status.items()):
                        name = status_info["name"]
                        status = status_info["status"]
                        start = status_info.get("start_time")
                        
                        # Calculate progress based on status
                        if status == "done":
                            progress = 100
                            status_icon = "✓"
                            status_text = "Done"
                        elif status == "error":
                            progress = 100
                            status_icon = "✗"
                            status_text = "Error"
                        elif status == "processing":
                            # Estimate progress based on elapsed time (rough estimate)
                            # Assume average video takes ~30 seconds to process
                            if start:
                                elapsed = current_time - start
                                estimated_duration = 30  # seconds
                                progress = min(95, int((elapsed / estimated_duration) * 100))
                            else:
                                progress = 5
                            status_icon = "⏳"
                            status_text = "Processing"
                        else:  # pending
                            progress = 0
                            status_icon = "⏸"
                            status_text = "Pending"
                        
                        # Get producer progress from status dict
                        producer_prog = 0
                        if "frames_sent" in status_info and "total_frames" in status_info:
                            total_frames = status_info.get("total_frames", 1)
                            frames_sent = status_info.get("frames_sent", 0)
                            if total_frames > 0:
                                producer_prog = min(100, int((frames_sent * 100) / total_frames))
                        else:
                            # Try to read from progress file as fallback
                            try:
                                with open(progress_file, 'r') as f:
                                    file_data = json.load(f)
                                    for v in file_data.get("videos", []):
                                        if v.get("video_id") == video_id:
                                            producer_prog = v.get("producer_progress", 0)
                                            break
                            except:
                                pass
                        
                        # CRITICAL: Never let producer progress decrease - use maximum seen
                        if video_id in max_producer_progress:
                            if producer_prog > max_producer_progress[video_id]:
                                max_producer_progress[video_id] = producer_prog
                            producer_prog = max_producer_progress[video_id]
                        else:
                            max_producer_progress[video_id] = producer_prog
                        
                        # Get existing stream_progress from file (preserve what stream processor wrote)
                        existing_video = existing_videos.get(video_id)
                        stream_prog = existing_video.get("stream_progress", 0) if existing_video else 0
                        
                        progress_data["videos"].append({
                            "video_id": video_id,
                            "name": name,
                            "producer_progress": producer_prog,
                            "stream_progress": stream_prog,  # PRESERVE from existing file!
                            "status": status,
                            "icon": status_icon,
                            "text": status_text
                        })
                    
                    # Write to file for run_full_test.sh with file locking
                    for attempt in range(max_retries):
                        try:
                            with open(progress_file, 'w') as f:
                                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                                json.dump(progress_data, f)
                                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                            break
                        except (IOError, OSError):
                            if attempt < max_retries - 1:
                                time.sleep(retry_delay)
                                continue
                            # Last attempt failed - skip
                            break
                
                # Also print to stdout (for logs)
                lines_to_clear = total_videos
                print(f"\033[{lines_to_clear}A", end="")  # Move up N lines
                
                with progress_lock:
                    for i, (video_id, status_info) in enumerate(sorted(video_status.items())):
                        name = status_info["name"]
                        status = status_info["status"]
                        start = status_info.get("start_time")
                        
                        # Calculate progress based on status
                        if status == "done":
                            progress = 100
                            status_icon = "✓"
                            status_text = "Done"
                        elif status == "error":
                            progress = 100
                            status_icon = "✗"
                            status_text = "Error"
                        elif status == "processing":
                            if start:
                                elapsed = current_time - start
                                estimated_duration = 30
                                progress = min(95, int((elapsed / estimated_duration) * 100))
                            else:
                                progress = 5
                            status_icon = "⏳"
                            status_text = "Processing"
                        else:
                            progress = 0
                            status_icon = "⏸"
                            status_text = "Pending"
                        
                        bar_length = 30
                        filled = int((progress * bar_length) / 100)
                        bar = "█" * filled + "░" * (bar_length - filled)
                        print(f"\r\033[K{status_icon} {name[:40]:<40} [{bar}] {progress:3d}% {status_text}", flush=False)
                
                print(f"\033[{lines_to_clear}B", end="", flush=True)
                last_update = current_time
            
            # Small sleep to avoid busy waiting
            time.sleep(0.1)
        
        # Final progress bars update (all at 100%)
        lines_to_clear = total_videos
        print(f"\033[{lines_to_clear}A", end="")  # Move up N lines
        
        with progress_lock:
            for i, (video_id, status_info) in enumerate(sorted(video_status.items())):
                name = status_info["name"]
                status = status_info["status"]
                
                if status == "done":
                    status_icon = "✓"
                    status_text = "Done"
                elif status == "error":
                    status_icon = "✗"
                    status_text = "Error"
                else:
                    status_icon = "✓"
                    status_text = "Done"
                
                # Final progress bar (100%)
                bar_length = 30
                bar = "█" * bar_length
                print(f"\r\033[K{status_icon} {name[:40]:<40} [{bar}] 100% {status_text}", flush=False)
        
        # Move cursor back down and print newline
        print(f"\033[{lines_to_clear}B", flush=True)
        print("")  # Newline after progress bars
    
    # Summary - only print after all videos are done
    print(f"\n{'='*60}")
    print("✓ All Videos Processed")
    print(f"{'='*60}")
    successful = sum(1 for _, success in results if success)
    print(f"Processed: {successful}/{len(results)} videos successfully")
    
    # Show detailed results
    for video_name, success in results:
        status = "✓" if success else "✗"
        print(f"  {status} {video_name}")
    
    # Show any errors
    errors = [(v["name"], v["error"]) for v in video_status.values() if v["status"] == "error" and v["error"]]
    if errors:
        print(f"\nErrors:")
        for name, error in errors:
            print(f"  ✗ {name}: {error}")
    
    print(f"\n{'='*60}")
    print("Next Steps:")
    print("1. Check the fire detection stream terminal for detection results")
    print("2. Check the consumer terminal for S3 upload confirmations")
    print("3. Check the clips/ directory for extracted video clips")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
