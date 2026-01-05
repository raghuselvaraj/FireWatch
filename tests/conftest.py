"""Pytest configuration and fixtures."""
import pytest
import numpy as np
import cv2
from unittest.mock import Mock, MagicMock
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def sample_frame():
    """Create a sample frame (numpy array) for testing."""
    # Create a 640x480 RGB frame
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    return frame


@pytest.fixture
def sample_frame_bgr():
    """Create a sample BGR frame for OpenCV."""
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    return frame


@pytest.fixture
def sample_frame_data():
    """Create sample base64-encoded frame data."""
    # Create a small test image
    frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    _, buffer = cv2.imencode('.jpg', frame)
    import base64
    return base64.b64encode(buffer.tobytes()).decode('utf-8')


@pytest.fixture
def sample_kafka_message():
    """Create a sample Kafka message."""
    return {
        "video_id": "test_video_1",
        "frame_number": 0,
        "timestamp": "2024-01-01T00:00:00",
        "fps": 30.0,
        "frame_data": "base64_encoded_data",
        "width": 640,
        "height": 480
    }


@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka producer."""
    producer = Mock()
    producer.send = Mock(return_value=Mock(get=Mock(return_value=Mock(
        topic="test-topic",
        partition=0,
        offset=123
    ))))
    producer.flush = Mock()
    producer.close = Mock()
    return producer


@pytest.fixture
def mock_kafka_consumer():
    """Mock Kafka consumer."""
    consumer = Mock()
    consumer.__iter__ = Mock(return_value=iter([]))
    consumer.close = Mock()
    return consumer


@pytest.fixture
def mock_s3_client():
    """Mock S3 client."""
    s3_client = Mock()
    s3_client.upload_file = Mock()
    s3_client.head_bucket = Mock()
    return s3_client


@pytest.fixture
def mock_fire_detect_nn_model():
    """Mock fire-detect-nn model."""
    model = Mock()
    model.eval = Mock()
    model.to = Mock(return_value=model)
    model.__call__ = Mock(return_value=Mock(
        item=Mock(return_value=0.75)  # 75% fire probability
    ))
    return model


@pytest.fixture
def mock_yolo_model():
    """Mock YOLOv8 model."""
    model = Mock()
    model.predict = Mock(return_value=[Mock(
        boxes=Mock(
            xyxy=[[[10, 10, 100, 100]]],
            conf=[[0.85]],
            cls=[[0]]
        ),
        names={0: "fire"}
    )])
    return model

