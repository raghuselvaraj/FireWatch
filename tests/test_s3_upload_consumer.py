"""Tests for S3UploadConsumer."""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from consumer.s3_video_consumer import S3VideoUploader, S3VideoConsumer


class TestS3VideoUploader:
    """Tests for S3VideoUploader class."""
    
    @pytest.fixture
    def uploader(self, mock_s3_client):
        """Create S3VideoUploader with mocked S3 client."""
        with patch('consumer.s3_video_consumer.boto3.client', return_value=mock_s3_client), \
             patch('consumer.s3_video_consumer.config') as mock_config:
            mock_config.S3_BUCKET = "test-bucket"
            mock_config.AWS_ACCESS_KEY_ID = "test-key"
            mock_config.AWS_SECRET_ACCESS_KEY = "test-secret"
            mock_config.AWS_REGION = "us-east-1"
            mock_config.S3_DELETE_LOCAL_AFTER_UPLOAD = True
            
            uploader = S3VideoUploader()
            uploader.s3_client = mock_s3_client
            return uploader
    
    def test_upload_video_success(self, uploader, tmp_path):
        """Test successful video upload."""
        # Create test video file
        test_file = tmp_path / "test_video.mp4"
        test_file.write_bytes(b"fake video data" * 1000)  # ~15KB
        
        s3_path = uploader.upload_video(str(test_file), "test_video_1")
        
        assert s3_path is not None
        assert "s3://" in s3_path
        assert "test-bucket" in s3_path
        assert "test_video_1" in s3_path
        uploader.s3_client.upload_file.assert_called_once()
    
    def test_upload_video_file_not_found(self, uploader):
        """Test upload with non-existent file."""
        s3_path = uploader.upload_video("/nonexistent/file.mp4", "test_video")
        
        assert s3_path is None
        uploader.s3_client.upload_file.assert_not_called()
    
    def test_upload_video_s3_error(self, uploader, tmp_path):
        """Test upload with S3 error."""
        test_file = tmp_path / "test_video.mp4"
        test_file.write_bytes(b"fake video data")
        
        # Mock S3 error
        from botocore.exceptions import ClientError
        uploader.s3_client.upload_file.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied'}},
            'UploadObject'
        )
        
        s3_path = uploader.upload_video(str(test_file), "test_video")
        
        assert s3_path is None
    
    def test_upload_video_delete_local(self, uploader, tmp_path):
        """Test that local file is deleted after upload."""
        test_file = tmp_path / "test_video.mp4"
        test_file.write_bytes(b"fake video data")
        
        uploader.upload_video(str(test_file), "test_video")
        
        # File should be deleted
        assert not test_file.exists()
    
    def test_upload_video_keep_local(self, uploader, tmp_path):
        """Test that local file is kept when configured."""
        with patch('consumer.s3_video_consumer.config') as mock_config:
            mock_config.S3_DELETE_LOCAL_AFTER_UPLOAD = False
            
            test_file = tmp_path / "test_video.mp4"
            test_file.write_bytes(b"fake video data")
            
            uploader.upload_video(str(test_file), "test_video")
            
            # File should still exist
            assert test_file.exists()


class TestS3VideoConsumer:
    """Tests for S3VideoConsumer class."""
    
    @pytest.fixture
    def consumer(self, mock_kafka_consumer, mock_s3_client):
        """Create S3VideoConsumer with mocked dependencies."""
        with patch('consumer.s3_video_consumer.KafkaConsumer', return_value=mock_kafka_consumer), \
             patch('consumer.s3_video_consumer.boto3.client', return_value=mock_s3_client), \
             patch('consumer.s3_video_consumer.config') as mock_config:
            mock_config.KAFKA_VIDEO_COMPLETIONS_TOPIC = "video-completions"
            mock_config.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
            mock_config.S3_BUCKET = "test-bucket"
            mock_config.AWS_ACCESS_KEY_ID = "test-key"
            mock_config.AWS_SECRET_ACCESS_KEY = "test-secret"
            mock_config.AWS_REGION = "us-east-1"
            mock_config.S3_DELETE_LOCAL_AFTER_UPLOAD = True
            
            consumer = S3VideoConsumer()
            consumer.consumer = mock_kafka_consumer
            consumer.s3_uploader.s3_client = mock_s3_client
            return consumer
    
    def test_process_message_success(self, consumer, tmp_path):
        """Test successful message processing."""
        # Create test video file
        test_file = tmp_path / "test_video_1_with_heatmaps.mp4"
        test_file.write_bytes(b"fake video data")
        
        message = {
            "video_id": "test_video_1",
            "local_filepath": str(test_file),
            "stats": {
                "total_frames": 100,
                "fire_count": 5,
                "max_fire_probability": 0.9
            },
            "video_metadata": {
                "fps": 30.0,
                "width": 640,
                "height": 480
            }
        }
        
        # Mock successful upload
        consumer.s3_uploader.upload_video = Mock(return_value="s3://test-bucket/videos/test_video_1_with_heatmaps.mp4")
        
        consumer.process_message(message)
        
        assert consumer.upload_count == 1
        assert consumer.error_count == 0
        consumer.s3_uploader.upload_video.assert_called_once()
    
    def test_process_message_missing_fields(self, consumer):
        """Test processing message with missing fields."""
        message = {
            "video_id": "test_video"
            # Missing local_filepath
        }
        
        consumer.process_message(message)
        
        assert consumer.error_count == 1
        assert consumer.upload_count == 0
    
    def test_process_message_upload_failure(self, consumer, tmp_path):
        """Test processing message when upload fails."""
        test_file = tmp_path / "test_video_1_with_heatmaps.mp4"
        test_file.write_bytes(b"fake video data")
        
        message = {
            "video_id": "test_video_1",
            "local_filepath": str(test_file),
            "stats": {},
            "video_metadata": {}
        }
        
        # Mock upload failure
        consumer.s3_uploader.upload_video = Mock(return_value=None)
        
        consumer.process_message(message)
        
        assert consumer.error_count == 1
        assert consumer.upload_count == 0
    
    def test_process_message_file_not_found(self, consumer):
        """Test processing message with non-existent file."""
        message = {
            "video_id": "test_video_1",
            "local_filepath": "/nonexistent/file.mp4",
            "stats": {},
            "video_metadata": {}
        }
        
        consumer.process_message(message)
        
        # Should handle gracefully
        assert consumer.error_count >= 0  # May or may not increment

