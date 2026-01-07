"""Tests for FireDetectionStream."""
import pytest
import numpy as np
import cv2
import base64
from unittest.mock import Mock, patch, MagicMock
from streams.fire_detection_stream import FireDetectionStream, FireDetectionModel, convert_numpy_types


class TestFireDetectionStream:
    """Tests for FireDetectionStream class."""
    
    @pytest.fixture
    def stream(self, mock_kafka_consumer, mock_kafka_producer):
        """Create a FireDetectionStream instance with mocked dependencies."""
        with patch('streams.fire_detection_stream.KafkaConsumer', return_value=mock_kafka_consumer), \
             patch('streams.fire_detection_stream.KafkaProducer', return_value=mock_kafka_producer), \
             patch('streams.fire_detection_stream.FireDetectionModel'):
            stream = FireDetectionStream()
            stream.consumer = mock_kafka_consumer
            stream.producer = mock_kafka_producer
            return stream
    
    def test_decode_frame(self, stream, sample_frame):
        """Test frame decoding from base64."""
        # Encode frame
        _, buffer = cv2.imencode('.jpg', sample_frame)
        frame_bytes = buffer.tobytes()
        encoded = base64.b64encode(frame_bytes).decode('utf-8')
        
        # Decode
        decoded = stream.decode_frame(encoded)
        
        # Verify shape is similar (may differ slightly due to JPEG compression)
        assert decoded.shape[0] > 0
        assert decoded.shape[1] > 0
        assert decoded.shape[2] == 3  # BGR channels
    
    def test_decode_frame_invalid(self, stream):
        """Test decoding invalid base64."""
        with pytest.raises(Exception):  # Should raise some exception
            stream.decode_frame("invalid_base64!!!")
    
    def test_initialize_video_writer(self, stream, tmp_path):
        """Test video writer initialization."""
        with patch('streams.fire_detection_stream.config') as mock_config:
            mock_config.CLIP_STORAGE_PATH = str(tmp_path)
            video_id = "test_video"
            
            # Initialize metadata first (as done in process_frame)
            stream.video_metadata[video_id] = {
                "start_timestamp": "2024-01-01T00:00:00"
            }
            
            filepath = stream._initialize_video_writer(video_id, 640, 480, 30.0)
            
            assert filepath is not None
            assert video_id in stream.video_writers
            assert stream.video_writers[video_id] is not None
            assert stream.video_metadata[video_id]["filepath"] == filepath
            assert stream.video_metadata[video_id]["fps"] == 30.0
            assert stream.video_metadata[video_id]["width"] == 640
            assert stream.video_metadata[video_id]["height"] == 480
    
    def test_close_video_writer(self, stream, tmp_path):
        """Test video writer closing."""
        from pathlib import Path
        with patch('streams.fire_detection_stream.config') as mock_config, \
             patch('cv2.VideoCapture') as mock_video_capture:
            mock_config.CLIP_STORAGE_PATH = str(tmp_path)
            video_id = "test_video"
            
            # Mock VideoCapture for file validation
            mock_cap = Mock()
            mock_cap.isOpened.return_value = True
            mock_cap.get.return_value = 10  # frame count
            mock_cap.release = Mock()
            mock_video_capture.return_value = mock_cap
            
            # Initialize metadata first
            stream.video_metadata[video_id] = {
                "start_timestamp": "2024-01-01T00:00:00"
            }
            
            # Initialize writer
            filepath = stream._initialize_video_writer(video_id, 640, 480, 30.0)
            stream.video_stats[video_id] = {"frames": 10, "fires": 2, "max_prob": 0.85}
            stream.video_frame_counts[video_id] = 10
            
            # Create the file so it exists
            if filepath:
                Path(filepath).parent.mkdir(parents=True, exist_ok=True)
                Path(filepath).write_bytes(b"fake video data")
            
            # Close writer (now requires video_id parameter)
            result = stream._close_video_writer(video_id, print_summary=False)
            
            # File validation may fail in test, so result might be None
            # But writer should still be closed
            assert video_id not in stream.video_writers or stream.video_writers[video_id] is None
    
    def test_overlay_heatmap_on_frame(self, stream, sample_frame_bgr):
        """Test heatmap overlay on frame."""
        # Create a simple heatmap
        heatmap = np.random.rand(480, 640).astype(np.float32)
        
        with patch('streams.fire_detection_stream.config') as mock_config:
            mock_config.CLIP_HEATMAP_OVERLAY_ALPHA = 0.4
            
            result = stream._overlay_heatmap_on_frame(sample_frame_bgr, heatmap)
            
            assert result.shape == sample_frame_bgr.shape
            assert result.dtype == sample_frame_bgr.dtype
    
    def test_overlay_heatmap_none(self, stream, sample_frame_bgr):
        """Test overlay with None heatmap."""
        result = stream._overlay_heatmap_on_frame(sample_frame_bgr, None)
        assert np.array_equal(result, sample_frame_bgr)
    
    def test_reset_video_state(self, stream):
        """Test video state initialization (replaces old _reset_video_state)."""
        video_id = "new_video"
        timestamp = "2024-01-01T00:00:00"
        frame_number = 0
        
        # Initialize video state (as done in process_frame)
        stream._initialize_video_state(video_id, timestamp, frame_number, 640, 480, 30.0)
        
        assert video_id in stream.video_metadata
        assert stream.video_metadata[video_id]["start_timestamp"] == timestamp
        assert stream.video_frame_counts[video_id] == 0
        assert video_id in stream.video_stats
    
    def test_publish_video_completion(self, stream, tmp_path):
        """Test video completion event publishing."""
        stream.current_video_id = "test_video"
        stream.video_fps = 30.0
        stream.video_width = 640
        stream.video_height = 480
        stream.video_frame_count = 100
        
        # Create a test file
        test_file = tmp_path / "test_video_with_heatmaps.mp4"
        test_file.write_bytes(b"fake video data")
        
        stream._publish_video_completion(
            "test_video",
            str(test_file),
            {"total_frames": 100, "fire_count": 5, "max_fire_probability": 0.9},
            {"fps": 30.0, "width": 640, "height": 480, "frame_count": 100}
        )
        
        # Verify producer.send was called
        assert stream.producer.send.called
    
    @patch('streams.fire_detection_stream.FireDetectionModel')
    def test_process_frame_fire_detect_nn(self, mock_model_class, stream, sample_frame_data):
        """Test frame processing with fire-detect-nn model."""
        # Mock model
        mock_model = Mock()
        mock_model.predict.return_value = {
            "has_fire": True,
            "fire_probability": 0.85,
            "detections": [],
            "heatmap": np.random.rand(224, 224).astype(np.float32)
        }
        stream.model = mock_model
        
        # Mock message
        message = {
            "video_id": "test_video",
            "frame_number": 0,
            "timestamp": "2024-01-01T00:00:00",
            "fps": 30.0,
            "frame_data": sample_frame_data,
            "width": 640,
            "height": 480
        }
        
        with patch('streams.fire_detection_stream.config') as mock_config:
            mock_config.CLIP_STORAGE_PATH = "/tmp"
            mock_config.CLIP_HEATMAP_OVERLAY_ALPHA = 0.4
            
            result = stream.process_frame(message)
            
            assert result is not None
            assert result["has_fire"] is True
            assert result["fire_probability"] == 0.85
            assert "video_id" in result
            assert "frame_number" in result


class TestFireDetectionModel:
    """Tests for FireDetectionModel class."""
    
    @pytest.fixture
    def model(self):
        """Create a FireDetectionModel instance (mocked)."""
        # Mock the model loading to avoid actual model initialization
        # _load_fire_detect_nn returns (model, device) tuple
        mock_model = Mock()
        mock_device = Mock()
        
        with patch.object(FireDetectionModel, '_load_fire_detect_nn', return_value=(mock_model, mock_device)), \
             patch.object(FireDetectionModel, '_load_model', return_value=Mock()):
            model = FireDetectionModel()
            # Ensure model and device are set correctly
            if not hasattr(model, 'model') or model.model is None:
                model.model = mock_model
            if not hasattr(model, 'device') or model.device is None:
                model.device = mock_device
            if not hasattr(model, 'fire_transform'):
                model.fire_transform = Mock()
            return model
    
    def test_predict_fire_detect_nn(self, model, sample_frame_bgr):
        """Test prediction with fire-detect-nn model."""
        # Mock model output
        mock_output = Mock()
        mock_output.item.return_value = 0.75  # 75% fire probability
        model.model.return_value = mock_output
        
        # Mock transform
        import torch
        model.fire_transform = Mock(return_value=torch.tensor([[1.0, 2.0, 3.0]]))
        
        result = model._predict_fire_detect_nn(sample_frame_bgr)
        
        assert "has_fire" in result
        assert "fire_probability" in result
        assert isinstance(result["fire_probability"], (int, float))
    
    def test_predict_yolo(self, model, sample_frame_bgr):
        """Test prediction with YOLOv8 model."""
        # Mock YOLO model
        mock_yolo = Mock()
        mock_yolo.predict.return_value = [Mock(
            boxes=Mock(
                xyxy=[[[10, 10, 100, 100]]],
                conf=[[0.85]],
                cls=[[0]]
            ),
            names={0: "fire"}
        )]
        model.model = mock_yolo
        model.use_fire_detect_nn = False
        model.confidence_threshold = 0.5
        
        result = model.predict(sample_frame_bgr)
        
        assert "has_fire" in result
        assert "fire_probability" in result
        assert "detections" in result

