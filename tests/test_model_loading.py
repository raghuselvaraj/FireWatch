"""Tests for model loading."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from streams.fire_detection_stream import FireDetectionModel


class TestModelLoading:
    """Tests for model loading functionality."""
    
    @patch('streams.fire_detection_stream.config')
    def test_fire_detect_nn_model_loading(self, mock_config):
        """Test fire-detect-nn model loading."""
        mock_config.ML_MODEL_TYPE = "fire-detect-nn"
        mock_config.ML_MODEL_SOURCE = "fire-detect-nn"
        mock_config.FIRE_DETECT_NN_DIR = "fire-detect-nn"
        mock_config.FIRE_DETECT_NN_WEIGHTS = "fire-detect-nn/weights/firedetect-densenet121-pretrained.pt"
        mock_config.CONFIDENCE_THRESHOLD = 0.5
        mock_config.IOU_THRESHOLD = 0.45
        
        # Mock fire-detect-nn imports
        with patch('streams.fire_detection_stream.FIRE_DETECT_NN_AVAILABLE', True), \
             patch('streams.fire_detection_stream.FireDetectionModel._load_fire_detect_nn') as mock_load:
            mock_model = Mock()
            mock_device = Mock()
            mock_load.return_value = (mock_model, mock_device)
            
            model = FireDetectionModel()
            
            assert model.use_fire_detect_nn is True
            assert model.model == mock_model
            assert model.device == mock_device
    
    @patch('streams.fire_detection_stream.config')
    def test_yolo_model_loading(self, mock_config):
        """Test YOLOv8 model loading."""
        mock_config.ML_MODEL_TYPE = "ultralytics"
        mock_config.ML_MODEL_SOURCE = "local"
        mock_config.ML_MODEL_PATH = "models/test_model.pt"
        mock_config.ML_MODEL_NAME = "yolov8n.pt"
        mock_config.CONFIDENCE_THRESHOLD = 0.25
        mock_config.IOU_THRESHOLD = 0.45
        
        # Mock YOLO loading
        with patch('streams.fire_detection_stream.YOLO') as mock_yolo_class:
            mock_yolo = Mock()
            mock_yolo_class.return_value = mock_yolo
            
            model = FireDetectionModel()
            
            assert model.use_fire_detect_nn is False
            assert model.model == mock_yolo
    
    @patch('streams.fire_detection_stream.config')
    def test_model_configuration_defaults(self, mock_config):
        """Test model configuration with defaults."""
        mock_config.ML_MODEL_TYPE = "fire-detect-nn"
        mock_config.ML_MODEL_SOURCE = "fire-detect-nn"
        mock_config.CONFIDENCE_THRESHOLD = 0.5
        mock_config.IOU_THRESHOLD = 0.45
        
        with patch('streams.fire_detection_stream.FireDetectionModel._load_fire_detect_nn') as mock_load:
            mock_load.return_value = (Mock(), Mock())
            
            model = FireDetectionModel()
            
            assert model.confidence_threshold == 0.5
            assert model.iou_threshold == 0.45
            assert model.use_fire_detect_nn is True

