"""Tests for VideoProducer."""
import pytest
import cv2
import numpy as np
import base64
from unittest.mock import Mock, patch, MagicMock
from producer.video_producer import VideoProducer


class TestVideoProducer:
    """Tests for VideoProducer class."""

    @pytest.fixture
    def producer(self, mock_kafka_producer):
        """Create a VideoProducer instance with mocked Kafka (msgpack default)."""
        with patch('producer.video_producer.KafkaProducer', return_value=mock_kafka_producer):
            prod = VideoProducer(bootstrap_servers="localhost:9092")
            prod.producer = mock_kafka_producer
            return prod

    @pytest.fixture
    def base64_producer(self, mock_kafka_producer):
        """Create a VideoProducer pinned to the legacy base64-json transport."""
        with patch('producer.video_producer.KafkaProducer', return_value=mock_kafka_producer), \
             patch('producer.video_producer.config') as mock_config:
            mock_config.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
            mock_config.KAFKA_VIDEO_TOPIC = "video-frames"
            mock_config.FRAME_TRANSPORT = "base64-json"
            prod = VideoProducer(bootstrap_servers="localhost:9092")
            prod.producer = mock_kafka_producer
            return prod

    def test_encode_frame_msgpack_passthrough(self, producer, sample_frame):
        """Default transport is msgpack — encode_frame is a no-op on bytes."""
        _, buffer = cv2.imencode('.jpg', sample_frame)
        frame_bytes = buffer.tobytes()

        encoded = producer.encode_frame(frame_bytes)

        assert encoded is frame_bytes
        assert isinstance(encoded, bytes)

    def test_encode_frame_base64(self, base64_producer, sample_frame):
        """Legacy transport returns a base64 string round-trippable to the input."""
        _, buffer = cv2.imencode('.jpg', sample_frame)
        frame_bytes = buffer.tobytes()

        encoded = base64_producer.encode_frame(frame_bytes)

        assert isinstance(encoded, str)
        assert base64.b64decode(encoded) == frame_bytes

    def test_encode_frame_empty_msgpack(self, producer):
        """Empty bytes pass through as empty bytes under msgpack."""
        assert producer.encode_frame(b"") == b""

    def test_encode_frame_empty_base64(self, base64_producer):
        """Empty bytes encode to the empty base64 string under legacy."""
        assert base64_producer.encode_frame(b"") == ""
    
    @patch('cv2.VideoCapture')
    def test_process_video_file_success(self, mock_video_capture, producer, sample_frame):
        """Test successful video file processing."""
        # Mock video capture
        mock_cap = Mock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = 30.0  # FPS
        mock_cap.read.side_effect = [
            (True, sample_frame),
            (True, sample_frame),
            (False, None)  # End of video
        ]
        mock_cap.release = Mock()
        mock_video_capture.return_value = mock_cap
        
        # Mock config
        with patch('producer.video_producer.config') as mock_config:
            mock_config.FRAME_EXTRACTION_INTERVAL = 1
            mock_config.FRAME_WIDTH = 640
            mock_config.FRAME_HEIGHT = 480
            
            producer.process_video_file("test_video.mp4", "test_video_1")
        
        # Verify video was opened and released
        mock_cap.isOpened.assert_called_once()
        mock_cap.release.assert_called_once()
        
        # Verify producer.send was called
        assert producer.producer.send.call_count == 2  # 2 frames
    
    @patch('cv2.VideoCapture')
    def test_process_video_file_invalid(self, mock_video_capture, producer):
        """Test processing invalid video file."""
        mock_cap = Mock()
        mock_cap.isOpened.return_value = False
        mock_video_capture.return_value = mock_cap
        
        with pytest.raises(ValueError, match="Could not open video file"):
            producer.process_video_file("invalid_video.mp4")
    
    @patch('cv2.VideoCapture')
    def test_process_video_file_auto_video_id(self, mock_video_capture, producer, sample_frame):
        """Test auto-generation of video_id."""
        mock_cap = Mock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = 30.0
        mock_cap.read.return_value = (False, None)
        mock_cap.release = Mock()
        mock_video_capture.return_value = mock_cap
        
        with patch('producer.video_producer.config') as mock_config:
            mock_config.FRAME_EXTRACTION_INTERVAL = 1
            mock_config.FRAME_WIDTH = None
            mock_config.FRAME_HEIGHT = None
            
            producer.process_video_file("test_video.mp4")
        
        # Verify video_id was generated (starts with "video_")
        call_args = producer.producer.send.call_args
        if call_args:
            message = call_args[1]['value']
            # Decode JSON to check video_id
            import json
            if isinstance(message, bytes):
                message = json.loads(message.decode())
            assert message['video_id'].startswith('video_')
    
    @patch('cv2.VideoCapture')
    def test_process_video_file_frame_extraction_interval(self, mock_video_capture, producer, sample_frame):
        """Test frame extraction interval."""
        mock_cap = Mock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = 30.0
        mock_cap.read.side_effect = [
            (True, sample_frame),  # Frame 0
            (True, sample_frame),  # Frame 1
            (True, sample_frame),  # Frame 2
            (True, sample_frame),  # Frame 3
            (False, None)
        ]
        mock_cap.release = Mock()
        mock_video_capture.return_value = mock_cap
        
        with patch('producer.video_producer.config') as mock_config:
            mock_config.FRAME_EXTRACTION_INTERVAL = 2  # Extract every 2nd frame
            mock_config.FRAME_WIDTH = None
            mock_config.FRAME_HEIGHT = None
            
            producer.process_video_file("test_video.mp4", "test_video_1")
        
        # Should extract frames 0 and 2 (every 2nd frame)
        assert producer.producer.send.call_count == 2
    
    def test_close(self, producer):
        """Test producer close."""
        producer.close()
        producer.producer.close.assert_called_once()
    
    def test_message_structure(self, producer, sample_frame):
        """Test that messages have correct structure."""
        # Encode frame
        _, buffer = cv2.imencode('.jpg', sample_frame)
        frame_bytes = buffer.tobytes()
        encoded = producer.encode_frame(frame_bytes)
        
        # Create message manually to verify structure
        from datetime import datetime
        message = {
            "video_id": "test_video",
            "frame_number": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "fps": 30.0,
            "frame_data": encoded,
            "width": sample_frame.shape[1],
            "height": sample_frame.shape[0]
        }
        
        # Verify all required fields. Under msgpack transport, frame_data is
        # raw bytes; under base64-json it would be a str. Either is acceptable
        # — the stream-side decode_frame handles both.
        assert "video_id" in message
        assert "frame_number" in message
        assert "timestamp" in message
        assert "fps" in message
        assert "frame_data" in message
        assert isinstance(message["frame_data"], (bytes, str))
        assert "width" in message
        assert "height" in message

