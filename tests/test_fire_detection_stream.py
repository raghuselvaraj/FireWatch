"""Tests for FireDetectionStream and the model backends.

Phase 2 split FireDetectionStream and FireDetectionModel into per-concern
modules. These tests target the new module locations: KafkaConsumer/Producer
and config are patched in ``streams.stream``, and per-backend behavior is
exercised against ``streams.models.fire_detect_nn.FireDetectNN`` and
``streams.models.yolov8.YOLOv8Detector`` directly.
"""
import base64
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
import pytest

from streams import FireDetectionModel, FireDetectionStream  # re-exported from streams/__init__.py
from streams.models.fire_detect_nn import FireDetectNN
from streams.models.yolov8 import YOLOv8Detector


class TestFireDetectionStream:
    """Tests for FireDetectionStream class."""

    @pytest.fixture
    def stream(self, mock_kafka_consumer, mock_kafka_producer):
        """Create a FireDetectionStream instance with mocked Kafka + model."""
        with patch("streams.stream.KafkaConsumer", return_value=mock_kafka_consumer), \
             patch("streams.stream.KafkaProducer", return_value=mock_kafka_producer), \
             patch("streams.stream.FireDetectionModel"):
            stream = FireDetectionStream()
            stream.consumer = mock_kafka_consumer
            stream.producer = mock_kafka_producer
            return stream

    def test_decode_frame(self, stream, sample_frame):
        """Test frame decoding from base64."""
        _, buffer = cv2.imencode(".jpg", sample_frame)
        encoded = base64.b64encode(buffer.tobytes()).decode("utf-8")

        decoded = stream.decode_frame(encoded)

        # JPEG round-trip may alter pixel values; shape should be preserved.
        assert decoded.shape[0] > 0
        assert decoded.shape[1] > 0
        assert decoded.shape[2] == 3  # BGR channels

    def test_decode_frame_invalid(self, stream):
        with pytest.raises(Exception):
            stream.decode_frame("invalid_base64!!!")

    def test_initialize_video_writer(self, stream, tmp_path):
        """Initialize a writer end-to-end (this hits the real OpenCV codec probe)."""
        with patch("streams.stream.config") as mock_config:
            mock_config.CLIP_STORAGE_PATH = str(tmp_path)
            video_id = "test_video"
            stream.video_metadata[video_id] = {"start_timestamp": "2024-01-01T00:00:00"}

            filepath = stream._initialize_video_writer(video_id, 640, 480, 30.0)

            assert filepath is not None
            assert video_id in stream.video_writers
            assert stream.video_writers[video_id] is not None
            assert stream.video_metadata[video_id]["filepath"] == filepath
            assert stream.video_metadata[video_id]["fps"] == 30.0
            assert stream.video_metadata[video_id]["width"] == 640
            assert stream.video_metadata[video_id]["height"] == 480

    def test_close_video_writer(self, stream, tmp_path):
        """Close a writer and confirm cleanup. File-validation may fail in the
        sandboxed test env; the contract is that the writer slot is cleared."""
        with patch("streams.stream.config") as mock_config, \
             patch("cv2.VideoCapture") as mock_video_capture:
            mock_config.CLIP_STORAGE_PATH = str(tmp_path)
            video_id = "test_video"

            mock_cap = Mock()
            mock_cap.isOpened.return_value = True
            mock_cap.get.return_value = 10  # frame count
            mock_cap.release = Mock()
            mock_video_capture.return_value = mock_cap

            stream.video_metadata[video_id] = {"start_timestamp": "2024-01-01T00:00:00"}

            filepath = stream._initialize_video_writer(video_id, 640, 480, 30.0)
            stream.video_stats[video_id] = {"frames": 10, "fires": 2, "max_prob": 0.85}
            stream.video_frame_counts[video_id] = 10

            if filepath:
                Path(filepath).parent.mkdir(parents=True, exist_ok=True)
                Path(filepath).write_bytes(b"fake video data")

            stream._close_video_writer(video_id, print_summary=False)

            assert video_id not in stream.video_writers or stream.video_writers[video_id] is None

    def test_overlay_heatmap_on_frame(self, stream, sample_frame_bgr):
        heatmap = np.random.rand(480, 640).astype(np.float32)
        # The overlay helper reads CLIP_HEATMAP_OVERLAY_ALPHA from config; patch
        # it at the actual module that imports config (streams.pipeline.overlay).
        with patch("streams.pipeline.overlay.config") as mock_config:
            mock_config.CLIP_HEATMAP_OVERLAY_ALPHA = 0.4
            result = stream._overlay_heatmap_on_frame(sample_frame_bgr, heatmap)
        assert result.shape == sample_frame_bgr.shape
        assert result.dtype == sample_frame_bgr.dtype

    def test_overlay_heatmap_none(self, stream, sample_frame_bgr):
        result = stream._overlay_heatmap_on_frame(sample_frame_bgr, None)
        assert np.array_equal(result, sample_frame_bgr)

    def test_initialize_video_state(self, stream):
        video_id = "new_video"
        timestamp = "2024-01-01T00:00:00"
        stream._initialize_video_state(video_id, timestamp, 0, 640, 480, 30.0)

        assert video_id in stream.video_metadata
        assert stream.video_metadata[video_id]["start_timestamp"] == timestamp
        assert stream.video_frame_counts[video_id] == 0
        assert video_id in stream.video_stats

    def test_publish_video_completion(self, stream, tmp_path):
        test_file = tmp_path / "test_video_with_heatmaps.mp4"
        test_file.write_bytes(b"fake video data")

        stream._publish_video_completion(
            "test_video",
            str(test_file),
            {"total_frames": 100, "fire_count": 5, "max_fire_probability": 0.9},
            {"fps": 30.0, "width": 640, "height": 480, "frame_count": 100},
        )
        assert stream.producer.send.called

    def test_process_frame_fire_detect_nn(self, stream, sample_frame_data):
        mock_model = Mock()
        mock_model.predict.return_value = {
            "has_fire": True,
            "fire_probability": 0.85,
            "detections": [],
            "heatmap": np.random.rand(224, 224).astype(np.float32),
        }
        stream.model = mock_model

        message = {
            "video_id": "test_video",
            "frame_number": 0,
            "timestamp": "2024-01-01T00:00:00",
            "fps": 30.0,
            "frame_data": sample_frame_data,
            "width": 640,
            "height": 480,
        }

        with patch("streams.stream.config") as mock_config, \
             patch("streams.pipeline.overlay.config") as mock_overlay_config:
            mock_config.CLIP_STORAGE_PATH = "/tmp"
            mock_overlay_config.CLIP_HEATMAP_OVERLAY_ALPHA = 0.4

            result = stream.process_frame(message)

        assert result is not None
        assert result["has_fire"] is True
        assert result["fire_probability"] == 0.85
        assert "video_id" in result
        assert "frame_number" in result


class TestFireDetectNNBackend:
    """Tests for the fire-detect-nn backend (``FireDetectNN`` predict path).

    Note: the legacy ``FireDetectionModel._predict_fire_detect_nn`` private
    method is gone — the backend's ``predict`` does the same work.
    """

    @pytest.fixture
    def backend(self):
        """Build a FireDetectNN with the torch/fire-detect-nn loader skipped."""
        mock_model = Mock()
        mock_device = Mock()
        mock_transform = Mock()
        with patch("streams.models.fire_detect_nn.FireDetectNN._select_device",
                   return_value=mock_device), \
             patch("streams.models.fire_detect_nn.FireDetectNN._load_weights",
                   return_value=(mock_model, mock_transform)):
            backend = FireDetectNN(confidence_threshold=0.5)
        return backend

    def test_predict_returns_expected_keys(self, backend, sample_frame_bgr):
        import torch

        mock_output = Mock()
        mock_output.item.return_value = 0.75  # 75% fire probability
        # ``model(input_tensor)`` returns a tensor; we index ``[0]``.
        backend.model.return_value = [mock_output]
        backend.fire_transform = Mock(return_value=torch.tensor([[1.0, 2.0, 3.0]]))

        result = backend.predict(sample_frame_bgr)

        assert "has_fire" in result
        assert "fire_probability" in result
        assert isinstance(result["fire_probability"], (int, float))
        assert result["model_type"] == "fire-detect-nn"


class TestYOLOv8Backend:
    """Tests for the YOLOv8 backend (``YOLOv8Detector`` predict path)."""

    @pytest.fixture
    def backend(self):
        mock_yolo = Mock()
        with patch("streams.models.yolov8.YOLOv8Detector._load", return_value=mock_yolo):
            backend = YOLOv8Detector(
                model_path="models/test_model.pt",
                model_source="local",
                model_name="yolov8n.pt",
                confidence_threshold=0.5,
                iou_threshold=0.45,
            )
        return backend

    def test_predict_returns_expected_keys(self, backend, sample_frame_bgr):
        backend.model.predict.return_value = [
            Mock(
                boxes=Mock(
                    xyxy=[[[10, 10, 100, 100]]],
                    conf=[[0.85]],
                    cls=[[0]],
                ),
                names={0: "fire"},
            )
        ]
        result = backend.predict(sample_frame_bgr)
        assert "has_fire" in result
        assert "fire_probability" in result
        assert "detections" in result


class TestFireDetectionModelDispatcher:
    """Smoke test that the dispatcher's public API is intact."""

    @patch("streams.models.dispatcher.config")
    def test_dispatcher_predict_delegates_to_backend(self, mock_config, sample_frame_bgr):
        mock_config.ML_MODEL_TYPE = "fire-detect-nn"
        mock_config.ML_MODEL_SOURCE = "fire-detect-nn"
        mock_config.ML_MODEL_PATH = "models/fire_detection_model.pt"
        mock_config.ML_MODEL_NAME = "ignored"
        mock_config.CONFIDENCE_THRESHOLD = 0.5
        mock_config.IOU_THRESHOLD = 0.45
        mock_config.GRADCAM_EVERY_N_FIRE_FRAMES = 1

        with patch("streams.models.fire_detect_nn.FireDetectNN._select_device",
                   return_value=Mock()), \
             patch("streams.models.fire_detect_nn.FireDetectNN._load_weights",
                   return_value=(Mock(), Mock())):
            model = FireDetectionModel()

        sentinel = {"has_fire": False, "fire_probability": 0.0, "detections": []}
        model._backend.predict = Mock(return_value=sentinel)

        assert model.predict(sample_frame_bgr) is sentinel
