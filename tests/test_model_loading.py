"""Tests for model loading."""
from unittest.mock import Mock, patch

from streams.models.dispatcher import FireDetectionModel


class TestModelLoading:
    """Tests for the FireDetectionModel dispatcher's backend selection."""

    @patch("streams.models.dispatcher.config")
    def test_fire_detect_nn_model_loading(self, mock_config):
        """When ML_MODEL_TYPE=fire-detect-nn the dispatcher loads FireDetectNN."""
        mock_config.ML_MODEL_TYPE = "fire-detect-nn"
        mock_config.ML_MODEL_SOURCE = "fire-detect-nn"
        mock_config.ML_MODEL_PATH = "models/fire_detection_model.pt"
        mock_config.ML_MODEL_NAME = "ignored-for-this-backend"
        mock_config.CONFIDENCE_THRESHOLD = 0.5
        mock_config.IOU_THRESHOLD = 0.45
        mock_config.GRADCAM_EVERY_N_FIRE_FRAMES = 1

        mock_model = Mock()
        mock_device = Mock()
        mock_transform = Mock()

        # Patch the loader hooks used by FireDetectNN.__init__ so we don't
        # touch torch / fire-detect-nn at all during this unit test.
        with patch("streams.models.fire_detect_nn.FireDetectNN._select_device",
                   return_value=mock_device), \
             patch("streams.models.fire_detect_nn.FireDetectNN._load_weights",
                   return_value=(mock_model, mock_transform)):
            model = FireDetectionModel()

        assert model.use_fire_detect_nn is True
        assert model.model is mock_model
        assert model.device is mock_device
        assert model.fire_transform is mock_transform

    @patch("streams.models.dispatcher.config")
    def test_yolo_model_loading(self, mock_config):
        """When ML_MODEL_TYPE=ultralytics the dispatcher loads YOLOv8Detector."""
        mock_config.ML_MODEL_TYPE = "ultralytics"
        mock_config.ML_MODEL_SOURCE = "local"
        mock_config.ML_MODEL_PATH = "models/test_model.pt"
        mock_config.ML_MODEL_NAME = "yolov8n.pt"
        mock_config.CONFIDENCE_THRESHOLD = 0.25
        mock_config.IOU_THRESHOLD = 0.45

        mock_yolo = Mock()
        with patch("streams.models.yolov8.YOLOv8Detector._load", return_value=mock_yolo):
            model = FireDetectionModel()

        assert model.use_fire_detect_nn is False
        assert model.model is mock_yolo

    @patch("streams.models.dispatcher.config")
    def test_model_configuration_defaults(self, mock_config):
        """Threshold values are pulled from config and exposed on the dispatcher."""
        mock_config.ML_MODEL_TYPE = "fire-detect-nn"
        mock_config.ML_MODEL_SOURCE = "fire-detect-nn"
        mock_config.ML_MODEL_PATH = "models/fire_detection_model.pt"
        mock_config.ML_MODEL_NAME = "ignored-for-this-backend"
        mock_config.CONFIDENCE_THRESHOLD = 0.5
        mock_config.IOU_THRESHOLD = 0.45
        mock_config.GRADCAM_EVERY_N_FIRE_FRAMES = 1

        with patch("streams.models.fire_detect_nn.FireDetectNN._select_device",
                   return_value=Mock()), \
             patch("streams.models.fire_detect_nn.FireDetectNN._load_weights",
                   return_value=(Mock(), Mock())):
            model = FireDetectionModel()

        assert model.confidence_threshold == 0.5
        assert model.iou_threshold == 0.45
        assert model.use_fire_detect_nn is True

