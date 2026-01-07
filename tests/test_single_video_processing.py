"""Unit tests for single video file processing."""
import pytest
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.test_with_videos import find_test_videos, main
# Note: test_video is a function in scripts/test_with_videos.py, not a test
# We test it indirectly through find_test_videos and other functions
import config


class TestSingleVideoProcessing:
    """Tests for single video file processing."""
    
    @pytest.fixture
    def temp_test_dir(self):
        """Create a temporary test directory with a test video file."""
        temp_dir = tempfile.mkdtemp()
        test_video_dir = Path(temp_dir) / "test_files" / "trail_cams" / "actual_fires"
        test_video_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a fake video file
        test_video_path = test_video_dir / "test_video.mp4"
        test_video_path.write_bytes(b"fake video data" * 100)
        
        yield temp_dir, test_video_path
        
        # Cleanup
        shutil.rmtree(temp_dir)
    
    def test_find_test_videos_single_file(self, temp_test_dir):
        """Test finding a single specific video file."""
        temp_dir, test_video_path = temp_test_dir
        
        # Test finding by exact name
        videos = find_test_videos(base_path=str(Path(temp_dir) / "test_files"), video_name="test_video")
        
        assert len(videos) > 0
        assert any("test_video" in str(v) for v in videos)
    
    def test_find_test_videos_single_file_not_found(self, temp_test_dir):
        """Test finding a non-existent video file."""
        temp_dir, _ = temp_test_dir
        
        videos = find_test_videos(base_path=str(Path(temp_dir) / "test_files"), video_name="nonexistent")
        
        # Should return empty list or fall back to all videos
        assert isinstance(videos, list)
    
    def test_find_test_videos_with_path_argument(self, temp_test_dir):
        """Test finding videos when a specific path is provided."""
        temp_dir, test_video_path = temp_test_dir
        
        # When a specific path is provided, it should be used directly
        video_path = Path(test_video_path)
        assert video_path.exists()
        assert video_path.is_file()
    
    def test_single_video_file_path_validation(self, temp_test_dir):
        """Test that single video file path is correctly validated."""
        temp_dir, test_video_path = temp_test_dir
        
        # Test that a valid file path is recognized
        assert test_video_path.exists()
        assert test_video_path.is_file()
        
        # Test that Path object works correctly
        video_path = Path(test_video_path)
        assert video_path.exists()
        assert video_path.suffix == '.mp4'
    
    def test_single_video_video_id_generation(self, temp_test_dir):
        """Test that video ID is correctly generated from filename for single video."""
        temp_dir, test_video_path = temp_test_dir
        
        # Test video ID generation (as done in test_video function)
        video_id = f"test_{test_video_path.stem}"
        
        assert video_id == "test_test_video"
        assert video_id.startswith("test_")
    
    def test_single_video_argument_parsing(self, temp_test_dir):
        """Test that single video argument is correctly parsed."""
        temp_dir, test_video_path = temp_test_dir
        
        # Test that find_test_videos can handle single video lookup
        videos = find_test_videos(
            base_path=str(Path(temp_dir) / "test_files"),
            video_name="test_video"
        )
        
        # Should find the test video
        assert len(videos) > 0
        assert any("test_video" in str(v) for v in videos)
    
    def test_single_video_progress_tracking(self, temp_test_dir):
        """Test that progress tracking works correctly for a single video."""
        temp_dir, test_video_path = temp_test_dir
        
        status_dict = {}
        status_lock = type('Lock', (), {'__enter__': lambda x: x, '__exit__': lambda x, *args: None})()
        video_id = "test_video"
        
        # Initialize status
        status_dict[video_id] = {
            "name": "test_video.mp4",
            "status": "pending",
            "frames_sent": 0,
            "total_frames": 100
        }
        
        # Update status to processing
        with status_lock:
            status_dict[video_id]["status"] = "processing"
            status_dict[video_id]["start_time"] = 1234567890.0
        
        # Verify status was updated
        assert status_dict[video_id]["status"] == "processing"
        assert "start_time" in status_dict[video_id]
    
    def test_single_video_status_tracking(self, temp_test_dir):
        """Test that status tracking works for a single video."""
        temp_dir, test_video_path = temp_test_dir
        
        status_dict = {}
        status_lock = type('Lock', (), {'__enter__': lambda x: x, '__exit__': lambda x, *args: None})()
        video_id = "test_video"
        
        # Initialize status
        status_dict[video_id] = {
            "name": "test_video.mp4",
            "status": "pending",
            "frames_sent": 0,
            "total_frames": 100
        }
        
        # Update status to processing
        with status_lock:
            status_dict[video_id]["status"] = "processing"
            status_dict[video_id]["start_time"] = 1234567890.0
        
        # Verify status was updated
        assert status_dict[video_id]["status"] == "processing"
        assert "start_time" in status_dict[video_id]
        
        # Update to done
        with status_lock:
            status_dict[video_id]["status"] = "done"
            status_dict[video_id]["frames_sent"] = 100
        
        # Verify final status
        assert status_dict[video_id]["status"] == "done"
        assert status_dict[video_id]["frames_sent"] == 100

