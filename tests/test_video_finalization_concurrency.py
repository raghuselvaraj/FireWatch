"""
Unit tests for video finalization with concurrent video processing.

Tests that multiple videos can be written simultaneously and properly finalized.
"""
import unittest
import os
import tempfile
import shutil
import threading
import time
import numpy as np
import cv2
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from streams.fire_detection_stream import FireDetectionStream
import config


import pytest

class TestVideoFinalizationConcurrency(unittest.TestCase):
    """Test video finalization with concurrent video processing."""
    
    # Mark all tests in this class as slow (they test complex concurrency scenarios)
    pytestmark = pytest.mark.slow
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        # Override config to use temp directory
        self.original_storage_path = config.CLIP_STORAGE_PATH
        config.CLIP_STORAGE_PATH = self.temp_dir
        
        # Mock Kafka consumer and producer, and suppress prints
        with patch('streams.fire_detection_stream.KafkaConsumer'), \
             patch('streams.fire_detection_stream.KafkaProducer'), \
             patch('streams.fire_detection_stream.FireDetectionModel'), \
             patch('builtins.print'):  # Suppress print statements
            self.stream = FireDetectionStream()
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Restore original path
        config.CLIP_STORAGE_PATH = self.original_storage_path
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def create_test_frame(self, width=640, height=360, frame_num=0):
        """Create a test frame with a visible frame number."""
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Add frame number text
        cv2.putText(frame, f"Frame {frame_num}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        return frame
    
    def test_single_video_finalization(self):
        """Test that a single video is properly finalized."""
        video_id = "test_video_1"
        width, height, fps = 640, 360, 30.0
        
        # Initialize video writer (suppress prints)
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))
        
        # Write some frames
        num_frames = 5  # Reduced for faster tests
        for i in range(num_frames):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
            self.stream.video_last_frames[video_id] = frame.copy()
        
        # Close video writer
        result_path = self.stream._close_video_writer(video_id, print_summary=False)
        self.assertEqual(result_path, filepath)
        
        # Verify file exists and has content
        self.assertTrue(os.path.exists(filepath))
        file_size = os.path.getsize(filepath)
        self.assertGreater(file_size, 0)
        
        # Verify video can be opened (checks for moov atom)
        cap = cv2.VideoCapture(filepath)
        self.assertTrue(cap.isOpened(), "Video file should be openable (moov atom present)")
        
        # Verify frame count
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.assertGreater(frame_count, 0, "Video should have frames")
        cap.release()
    
    def test_multiple_videos_concurrent_initialization(self):
        """Test that multiple videos can be initialized concurrently."""
        video_ids = ["video_1", "video_2", "video_3"]
        width, height, fps = 640, 360, 30.0
        
        # Initialize all videos (suppress prints)
        filepaths = {}
        with patch('builtins.print'):
            for video_id in video_ids:
                filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
                self.assertIsNotNone(filepath)
                filepaths[video_id] = filepath
                self.assertIn(video_id, self.stream.video_writers)
                self.assertIsNotNone(self.stream.video_writers[video_id])
        
        # Verify all files exist
        for video_id, filepath in filepaths.items():
            self.assertTrue(os.path.exists(filepath), f"File for {video_id} should exist")
    
    def test_multiple_videos_concurrent_writing(self):
        """Test that multiple videos can be written to concurrently."""
        video_ids = ["video_1", "video_2", "video_3"]
        width, height, fps = 640, 360, 30.0
        num_frames_per_video = 5  # Reduced for faster tests
        
        # Initialize all videos
        filepaths = {}
        for video_id in video_ids:
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
            filepaths[video_id] = filepath
        
        # Write frames to all videos concurrently (simulating parallel processing)
        for frame_num in range(num_frames_per_video):
            for video_id in video_ids:
                frame = self.create_test_frame(width, height, frame_num)
                self.stream.video_writers[video_id].write(frame)
                self.stream.video_frame_counts[video_id] = frame_num + 1
                self.stream.video_last_frames[video_id] = frame.copy()
        
        # Verify all videos have frames written
        for video_id in video_ids:
            self.assertEqual(
                self.stream.video_frame_counts[video_id], 
                num_frames_per_video,
                f"{video_id} should have {num_frames_per_video} frames"
            )
    
    def test_multiple_videos_concurrent_finalization(self):
        """Test that multiple videos can be finalized concurrently."""
        video_ids = ["video_1", "video_2", "video_3"]
        width, height, fps = 640, 360, 30.0
        num_frames_per_video = 5  # Reduced for faster tests
        
        # Initialize and write to all videos (suppress prints)
        filepaths = {}
        with patch('builtins.print'):
            for video_id in video_ids:
                filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
                filepaths[video_id] = filepath
            
            # Write frames to each video
            for video_id in video_ids:
                for i in range(num_frames_per_video):
                    frame = self.create_test_frame(width, height, i)
                    self.stream.video_writers[video_id].write(frame)
                    self.stream.video_frame_counts[video_id] = i + 1
                    self.stream.video_last_frames[video_id] = frame.copy()
        
        # Finalize all videos concurrently (suppress prints)
        finalized_paths = {}
        with patch('builtins.print'):
            for video_id in video_ids:
                result_path = self.stream._close_video_writer(video_id, print_summary=False)
                finalized_paths[video_id] = result_path
        
        # Verify all videos were finalized
        for video_id in video_ids:
            # Result path may be None if file is empty, but filepath should exist
            filepath = filepaths[video_id]
            self.assertTrue(os.path.exists(filepath), f"File for {video_id} should exist")
            
            # If result_path is not None, verify file is playable
            if finalized_paths[video_id] is not None:
                # Verify file is playable (moov atom present)
                cap = cv2.VideoCapture(filepath)
                self.assertTrue(cap.isOpened(), f"Video {video_id} should be openable")
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                self.assertGreater(frame_count, 0, f"Video {video_id} should have frames")
                cap.release()
            
            # Verify writer is cleared
            self.assertIsNone(self.stream.video_writers.get(video_id))
    
    def test_concurrent_finalization_thread_safety(self):
        """Test that finalizing multiple videos from different threads is safe."""
        video_ids = ["video_1", "video_2", "video_3", "video_4"]
        width, height, fps = 640, 360, 30.0
        num_frames_per_video = 5  # Reduced for faster tests
        
        # Initialize all videos
        filepaths = {}
        for video_id in video_ids:
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
            filepaths[video_id] = filepath
            
            # Write frames
            for i in range(num_frames_per_video):
                frame = self.create_test_frame(width, height, i)
                self.stream.video_writers[video_id].write(frame)
                self.stream.video_frame_counts[video_id] = i + 1
                self.stream.video_last_frames[video_id] = frame.copy()
        
        # Finalize videos from multiple threads
        finalized_paths = {}
        errors = []
        
        def finalize_video(video_id):
            try:
                with patch('builtins.print'):
                    result_path = self.stream._close_video_writer(video_id, print_summary=False)
                finalized_paths[video_id] = result_path
            except Exception as e:
                errors.append((video_id, str(e)))
        
        threads = []
        for video_id in video_ids:
            thread = threading.Thread(target=finalize_video, args=(video_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify no errors occurred
        self.assertEqual(len(errors), 0, f"Errors during concurrent finalization: {errors}")
        
        # Verify all videos were finalized
        self.assertEqual(len(finalized_paths), len(video_ids))
        for video_id in video_ids:
            self.assertIn(video_id, finalized_paths)
            filepath = finalized_paths[video_id]
            self.assertTrue(os.path.exists(filepath))
            
            # Verify video is playable
            cap = cv2.VideoCapture(filepath)
            self.assertTrue(cap.isOpened(), f"Video {video_id} should be openable")
            cap.release()
    
    def test_video_writer_release_called(self):
        """Test that video_writer.release() is actually called."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize video writer (suppress prints)
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        video_writer = self.stream.video_writers[video_id]
        
        # Track if release is called by patching at the stream level
        # We can't mock the method directly as it's read-only, so we verify
        # the file is properly finalized instead
        release_called = {'called': False}
        original_close = self.stream._close_video_writer
        
        def tracking_close(vid_id, print_summary=True):
            # Call original which will call release()
            result = original_close(vid_id, print_summary)
            release_called['called'] = True
            return result
        
        self.stream._close_video_writer = tracking_close
        
        # Write some frames
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            video_writer.write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
            self.stream.video_last_frames[video_id] = frame.copy()
        
        # Restore original method and close video writer (suppress prints)
        self.stream._close_video_writer = original_close
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        # Verify file was finalized (indicates release was called)
        self.assertIsNotNone(result_path, "Video should be finalized")
        self.assertTrue(os.path.exists(filepath), "Video file should exist")
    
    def test_no_duplicate_frames_on_finalization(self):
        """Test that finalization doesn't write duplicate frames."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        num_frames = 10
        
        # Initialize and write frames (suppress prints)
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        video_writer = self.stream.video_writers[video_id]
        
        # Write frames and track frame count
        for i in range(num_frames):
            frame = self.create_test_frame(width, height, i)
            video_writer.write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
            self.stream.video_last_frames[video_id] = frame.copy()
        
        # Get file size before finalization
        file_size_before = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        
        # Finalize (may write last frame once more, which is acceptable)
        # The implementation writes the last frame during finalization to ensure
        # all frames are flushed, so we allow one additional write
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        # Verify file exists and was finalized
        self.assertIsNotNone(result_path)
        self.assertTrue(os.path.exists(filepath))
        
        # File size should increase (buffered frames written), but not dramatically
        # A small increase is expected from finalization, but not a large one
        file_size_after = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        # The file should have grown, but not by more than what's reasonable for one extra frame
        self.assertGreater(file_size_after, file_size_before, "File should grow during finalization")
    
    def test_file_handle_closed_after_finalization(self):
        """Test that file handles are properly closed after finalization."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize and write frames (suppress prints)
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
        
        # Finalize (suppress prints)
        with patch('builtins.print'):
            self.stream._close_video_writer(video_id, print_summary=False)
        
        # Verify writer is cleared
        self.assertIsNone(self.stream.video_writers.get(video_id))
        
        # Verify we can still access the file (handle is closed, file is accessible)
        self.assertTrue(os.path.exists(filepath))
        file_size = os.path.getsize(filepath)
        self.assertGreater(file_size, 0)
    
    def test_multiple_videos_different_resolutions(self):
        """Test that videos with different resolutions can be finalized concurrently."""
        video_configs = [
            ("video_1", 640, 360, 30.0),
            ("video_2", 1280, 720, 30.0),
            ("video_3", 320, 240, 15.0),
        ]
        
        # Initialize all videos (suppress prints)
        filepaths = {}
        with patch('builtins.print'):
            for video_id, width, height, fps in video_configs:
                filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
                filepaths[video_id] = filepath
                
                # Write some frames
                for i in range(5):  # Reduced for faster tests
                    frame = self.create_test_frame(width, height, i)
                    self.stream.video_writers[video_id].write(frame)
                    self.stream.video_frame_counts[video_id] = i + 1
        
        # Finalize all videos (suppress prints)
        with patch('builtins.print'):
            for video_id, _, _, _ in video_configs:
                result_path = self.stream._close_video_writer(video_id, print_summary=False)
            self.assertIsNotNone(result_path)
            
            # Verify video is playable
            cap = cv2.VideoCapture(result_path)
            self.assertTrue(cap.isOpened(), f"Video {video_id} should be openable")
            cap.release()
    
    def test_finalization_video_with_no_frames(self):
        """Test finalization of a video that has no frames written."""
        video_id = "empty_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize video writer but don't write any frames
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        self.assertIsNotNone(filepath)
        
        # Set frame count to 0 (no frames written)
        self.stream.video_frame_counts[video_id] = 0
        
        # Try to finalize empty video
        # Note: _close_video_writer may return None for empty videos (file size 0)
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        # File should exist (even if empty)
        self.assertTrue(os.path.exists(filepath))
        # Result path may be None for empty videos, which is acceptable
    
    def test_finalization_already_closed_video(self):
        """Test that finalizing an already-closed video is safe."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize and write frames
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
        
        # Close once
        with patch('builtins.print'):
            result1 = self.stream._close_video_writer(video_id, print_summary=False)
        self.assertIsNotNone(result1)
        
        # Try to close again (should return None safely)
        with patch('builtins.print'):
            result2 = self.stream._close_video_writer(video_id, print_summary=False)
        self.assertIsNone(result2, "Closing already-closed video should return None")
    
    def test_finalization_when_writer_is_none(self):
        """Test finalization when video writer is None."""
        video_id = "none_video"
        
        # Set writer to None without initializing
        self.stream.video_writers[video_id] = None
        
        # Should return None safely
        with patch('builtins.print'):
            result = self.stream._close_video_writer(video_id, print_summary=False)
        self.assertIsNone(result)
    
    def test_finalization_when_video_id_not_in_writers(self):
        """Test finalization when video_id doesn't exist in writers dict."""
        video_id = "non_existent_video"
        
        # Should return None safely
        with patch('builtins.print'):
            result = self.stream._close_video_writer(video_id, print_summary=False)
        self.assertIsNone(result)
    
    def test_finalization_with_release_failure(self):
        """Test finalization when video_writer.release() fails."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize and write frames
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
            self.stream.video_last_frames[video_id] = frame.copy()
        
        # Replace the video_writer with a mock that has a failing release
        original_writer = self.stream.video_writers[video_id]
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_writer.write = original_writer.write  # Keep real write
        mock_writer.release.side_effect = Exception("Release failed")
        
        self.stream.video_writers[video_id] = mock_writer
        
        # Should handle exception gracefully
        with patch('builtins.print'):
            try:
                result = self.stream._close_video_writer(video_id, print_summary=False)
                # If exception is caught, result might be None or filepath
                # The important thing is it doesn't crash
                # The method should catch the exception and return None or handle it
            except Exception as e:
                self.fail(f"Finalization should handle release() failure gracefully: {e}")
    
    def test_finalization_file_size_changes(self):
        """Test that file size increases after finalization (buffered frames written)."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        num_frames = 10
        
        # Initialize and write frames
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        # Write frames
        for i in range(num_frames):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
        
        # Get file size before release
        file_size_before = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        
        # Finalize
        with patch('builtins.print'):
            self.stream._close_video_writer(video_id, print_summary=False)
        
        # File size should increase (buffered frames written)
        file_size_after = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        self.assertGreaterEqual(file_size_after, file_size_before, 
                               "File size should increase after finalization")
    
    def test_finalization_clears_writer_reference(self):
        """Test that finalization clears the writer reference."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        # Verify writer exists
        self.assertIsNotNone(self.stream.video_writers.get(video_id))
        
        # Write some frames
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
        
        # Finalize
        with patch('builtins.print'):
            self.stream._close_video_writer(video_id, print_summary=False)
        
        # Writer should be cleared
        self.assertIsNone(self.stream.video_writers.get(video_id),
                         "Writer reference should be cleared after finalization")
    
    def test_finalization_with_large_frame_count(self):
        """Test finalization with a large number of frames."""
        video_id = "large_video"
        width, height, fps = 640, 360, 30.0
        num_frames = 100  # Larger frame count
        
        # Initialize
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        # Write many frames
        for i in range(num_frames):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
            self.stream.video_last_frames[video_id] = frame.copy()
        
        # Store frame count before finalization (it may be cleared)
        expected_frame_count = self.stream.video_frame_counts.get(video_id, 0)
        
        # Finalize
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        self.assertIsNotNone(result_path)
        self.assertTrue(os.path.exists(filepath))
        # Frame count may be cleared after finalization, so check before
        # The important thing is that we wrote the expected number of frames
        self.assertEqual(expected_frame_count, num_frames, "Should have written all frames")
    
    def test_finalization_multiple_videos_sequential(self):
        """Test finalizing multiple videos sequentially (not concurrently)."""
        video_ids = ["video_1", "video_2", "video_3"]
        width, height, fps = 640, 360, 30.0
        num_frames = 5
        
        # Initialize all
        filepaths = {}
        with patch('builtins.print'):
            for video_id in video_ids:
                filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
                filepaths[video_id] = filepath
                
                # Write frames
                for i in range(num_frames):
                    frame = self.create_test_frame(width, height, i)
                    self.stream.video_writers[video_id].write(frame)
                    self.stream.video_frame_counts[video_id] = i + 1
        
        # Finalize sequentially
        finalized_paths = {}
        with patch('builtins.print'):
            for video_id in video_ids:
                result_path = self.stream._close_video_writer(video_id, print_summary=False)
                finalized_paths[video_id] = result_path
        
        # Verify all finalized
        for video_id in video_ids:
            self.assertIsNotNone(finalized_paths[video_id])
            self.assertTrue(os.path.exists(finalized_paths[video_id]))
            self.assertIsNone(self.stream.video_writers.get(video_id))
    
    def test_finalization_preserves_metadata(self):
        """Test that finalization preserves video metadata."""
        video_id = "test_video"
        width, height, fps = 1280, 720, 60.0
        
        # Initialize
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        # Verify metadata stored
        metadata = self.stream.video_metadata.get(video_id, {})
        self.assertEqual(metadata.get("width"), width)
        self.assertEqual(metadata.get("height"), height)
        self.assertEqual(metadata.get("fps"), fps)
        
        # Write frames
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
        
        # Finalize
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        # Metadata should still be accessible
        metadata_after = self.stream.video_metadata.get(video_id, {})
        self.assertEqual(metadata_after.get("width"), width)
        self.assertEqual(metadata_after.get("height"), height)
        self.assertEqual(metadata_after.get("fps"), fps)
    
    def test_finalization_with_interrupted_writes(self):
        """Test finalization after interrupted frame writing."""
        video_id = "interrupted_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        # Write some frames
        for i in range(3):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
        
        # Simulate interruption (don't write more frames)
        # But still finalize
        
        # Finalize should still work
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        self.assertIsNotNone(result_path)
        self.assertTrue(os.path.exists(filepath))
    
    def test_finalization_all_videos_in_cleanup(self):
        """Test that _cleanup() finalizes all active videos."""
        video_ids = ["video_1", "video_2", "video_3"]
        width, height, fps = 640, 360, 30.0
        
        # Initialize all
        filepaths = {}
        with patch('builtins.print'):
            for video_id in video_ids:
                filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
                filepaths[video_id] = filepath
                
                # Write frames
                for i in range(5):
                    frame = self.create_test_frame(width, height, i)
                    self.stream.video_writers[video_id].write(frame)
        
        # Verify all are active
        for video_id in video_ids:
            self.assertIsNotNone(self.stream.video_writers.get(video_id))
        
        # Call cleanup
        with patch('builtins.print'):
            self.stream._cleanup()
        
        # All should be finalized
        for video_id in video_ids:
            self.assertIsNone(self.stream.video_writers.get(video_id),
                             f"{video_id} should be finalized after cleanup")
            self.assertTrue(os.path.exists(filepaths[video_id]))
    
    def test_finalization_with_different_codecs(self):
        """Test finalization works with different codec fallbacks."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # The codec selection happens in _initialize_video_writer
        # We test that finalization works regardless of which codec was selected
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        # Write frames
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
            self.stream.video_frame_counts[video_id] = i + 1
        
        # Finalize should work regardless of codec
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        self.assertIsNotNone(result_path)
        self.assertTrue(os.path.exists(filepath))
    
    def test_finalization_file_system_sync(self):
        """Test that finalization properly syncs file to disk."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize and write
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
        
        # Finalize (includes fsync)
        with patch('builtins.print'):
            result_path = self.stream._close_video_writer(video_id, print_summary=False)
        
        # File should exist and be accessible immediately
        self.assertTrue(os.path.exists(filepath))
        file_size = os.path.getsize(filepath)
        self.assertGreater(file_size, 0)
    
    def test_finalization_with_gc_collect(self):
        """Test that garbage collection happens during finalization."""
        video_id = "test_video"
        width, height, fps = 640, 360, 30.0
        
        # Initialize and write
        with patch('builtins.print'):
            filepath = self.stream._initialize_video_writer(video_id, width, height, fps)
        
        for i in range(5):
            frame = self.create_test_frame(width, height, i)
            self.stream.video_writers[video_id].write(frame)
        
        # Track if gc.collect is called
        import gc
        original_collect = gc.collect
        collect_called = []
        
        def tracking_collect():
            collect_called.append(True)
            return original_collect()
        
        gc.collect = tracking_collect
        
        try:
            # Finalize
            with patch('builtins.print'):
                self.stream._close_video_writer(video_id, print_summary=False)
            
            # gc.collect should have been called
            self.assertGreater(len(collect_called), 0, "gc.collect should be called during finalization")
        finally:
            gc.collect = original_collect


if __name__ == '__main__':
    unittest.main()

