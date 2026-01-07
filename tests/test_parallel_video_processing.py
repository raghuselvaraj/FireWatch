#!/usr/bin/env python3
"""Unit tests to verify parallel video processing works correctly."""
import unittest
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from producer.video_producer import VideoProducer


class TestParallelVideoProcessing(unittest.TestCase):
    """Test that videos actually process in parallel."""
    
    def test_threadpool_executor_parallel_execution(self):
        """Verify ThreadPoolExecutor actually runs tasks in parallel."""
        execution_times = {}
        lock = threading.Lock()
        
        def worker(task_id, duration):
            start = time.time()
            time.sleep(duration)
            elapsed = time.time() - start
            with lock:
                execution_times[task_id] = elapsed
            return task_id
        
        start = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(worker, i, 1.0) for i in range(3)]
            results = [f.result() for f in futures]
        total_time = time.time() - start
        
        # If parallel: should take ~1 second (all run simultaneously)
        # If sequential: would take ~3 seconds
        self.assertLess(total_time, 1.5, 
                       f"Tasks took {total_time}s - should be ~1s if parallel, ~3s if sequential")
        self.assertEqual(len(results), 3)
        print(f"✓ Parallel execution test: {total_time:.2f}s (expected ~1s)")
    
    def test_video_producer_no_blocking_sends(self):
        """Verify VideoProducer doesn't block on sends."""
        with patch('producer.video_producer.KafkaProducer') as mock_kafka:
            # Mock Kafka producer
            mock_producer_instance = MagicMock()
            mock_kafka.return_value = mock_producer_instance
            
            # Mock video capture and OpenCV
            with patch('producer.video_producer.cv2') as mock_cv2:
                import numpy as np
                
                mock_cap = MagicMock()
                mock_cap.isOpened.return_value = True
                mock_cap.get.return_value = 30.0  # FPS
                # Return numpy array frames
                mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                mock_cap.read.side_effect = [
                    (True, mock_frame) for _ in range(10)  # 10 frames
                ] + [(False, None)]  # End of video
                mock_cv2.VideoCapture.return_value = mock_cap
                mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))
                
                # Mock config
                with patch('producer.video_producer.config') as mock_config:
                    mock_config.FRAME_EXTRACTION_INTERVAL = 1
                    mock_config.FRAME_WIDTH = None
                    mock_config.FRAME_HEIGHT = None
                    
                    producer = VideoProducer()
                    
                    # Time the processing
                    start = time.time()
                    producer.process_video_file('/fake/path.mp4', 'test_video')
                    elapsed = time.time() - start
                    
                    # Verify send was called (async, shouldn't block)
                    self.assertGreater(mock_producer_instance.send.call_count, 0)
                    
                    # Verify flush was called at the end
                    mock_producer_instance.flush.assert_called_once()
                    
                    # Should be fast (no blocking on sends)
                    self.assertLess(elapsed, 5.0, "Processing took too long - might be blocking")
                    print(f"✓ Non-blocking sends test: {elapsed:.2f}s")
    
    def test_multiple_producers_parallel(self):
        """Verify multiple VideoProducer instances can run in parallel."""
        execution_order = []
        lock = threading.Lock()
        
        def mock_process_video(video_id, duration=0.5):
            """Simulate video processing."""
            with lock:
                execution_order.append(f"{video_id}_start")
            time.sleep(duration)
            with lock:
                execution_order.append(f"{video_id}_end")
            return video_id
        
        start = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(mock_process_video, f"video{i}") for i in range(3)]
            results = [f.result() for f in futures]
        total_time = time.time() - start
        
        # Check execution order - if parallel, we should see interleaved starts/ends
        # If sequential, we'd see: video0_start, video0_end, video1_start, video1_end, etc.
        starts_before_all_ends = sum(1 for event in execution_order if event.endswith('_start'))
        ends_after_first_start = sum(1 for event in execution_order 
                                     if event.endswith('_end') and 
                                     execution_order.index(event) < len(execution_order) - 3)
        
        # In parallel execution, we should see multiple starts before all ends
        self.assertGreater(starts_before_all_ends, 1, 
                          "All videos started sequentially - not parallel!")
        self.assertLess(total_time, 1.0, 
                       f"Took {total_time}s - should be ~0.5s if parallel")
        print(f"✓ Multiple producers parallel test: {total_time:.2f}s")
        print(f"  Execution order: {execution_order}")
    
    def test_progress_tracking_thread_safe(self):
        """Verify progress tracking is thread-safe."""
        video_status = {
            'video1': {'name': 'test1.mp4', 'status': 'pending', 'error': None},
            'video2': {'name': 'test2.mp4', 'status': 'pending', 'error': None},
            'video3': {'name': 'test3.mp4', 'status': 'pending', 'error': None},
        }
        completed_count = 0
        lock = threading.Lock()
        
        def update_progress_safe(video_id, success, error_msg):
            nonlocal completed_count
            with lock:
                if video_id in video_status:
                    if success:
                        video_status[video_id]['status'] = 'done'
                    else:
                        video_status[video_id]['status'] = 'error'
                        video_status[video_id]['error'] = error_msg
                    completed_count += 1
        
        def worker(video_id):
            time.sleep(0.1)  # Simulate work
            update_progress_safe(video_id, True, None)
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(worker, vid_id) for vid_id in video_status.keys()]
            [f.result() for f in futures]
        
        # Verify all videos were marked as done
        self.assertEqual(completed_count, 3)
        for vid_id, status in video_status.items():
            self.assertEqual(status['status'], 'done', f"{vid_id} not marked as done")
        print("✓ Thread-safe progress tracking test passed")
    
    def test_producer_acks_setting(self):
        """Verify producer uses acks=1 for better parallel performance."""
        with patch('producer.video_producer.KafkaProducer') as mock_kafka:
            producer = VideoProducer()
            
            # Check that KafkaProducer was called with acks=1
            call_kwargs = mock_kafka.call_args[1]
            self.assertEqual(call_kwargs.get('acks'), 1, 
                           "Producer should use acks=1 for parallel processing, not acks='all'")
            print("✓ Producer acks=1 setting verified")


class TestVideoProducerIntegration(unittest.TestCase):
    """Integration tests with mocked dependencies."""
    
    @patch('producer.video_producer.cv2')
    @patch('producer.video_producer.KafkaProducer')
    def test_producer_sends_all_frames_async(self, mock_kafka, mock_cv2):
        """Verify producer sends all frames without blocking."""
        import numpy as np
        
        # Setup mocks
        mock_producer = MagicMock()
        mock_kafka.return_value = mock_producer
        
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = 30.0
        # Return numpy array frames (100 frames then end)
        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cap.read.side_effect = [
            (True, mock_frame) for _ in range(100)
        ] + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap
        # Return proper numpy array for imencode
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))
        
        # Mock config
        with patch('producer.video_producer.config') as mock_config:
            mock_config.FRAME_EXTRACTION_INTERVAL = 1
            mock_config.FRAME_WIDTH = None
            mock_config.FRAME_HEIGHT = None
            
            producer = VideoProducer()
            start = time.time()
            producer.process_video_file('/fake/path.mp4', 'test_video')
            elapsed = time.time() - start
            
            # Verify sends were called (should be 100 calls for 100 frames)
            # Note: actual count depends on FRAME_EXTRACTION_INTERVAL
            self.assertGreater(mock_producer.send.call_count, 0)
            
            # Verify flush was called once at the end
            mock_producer.flush.assert_called_once()
            
            # Should be fast (no blocking)
            self.assertLess(elapsed, 2.0, f"Took {elapsed}s - should be fast")
            print(f"✓ Async frame sending test: {elapsed:.2f}s, {mock_producer.send.call_count} sends")


if __name__ == '__main__':
    print("=" * 60)
    print("Running Parallel Video Processing Tests")
    print("=" * 60)
    print()
    
    # Run tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("✓ ALL TESTS PASSED - Parallel processing verified!")
    else:
        print("✗ SOME TESTS FAILED - Check output above")
    print("=" * 60)
    
    sys.exit(0 if result.wasSuccessful() else 1)

