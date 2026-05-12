"""FireWatch backend loads a custom checkpoint and produces the canonical predict() dict."""
from pathlib import Path

import numpy as np
import pytest
import torch
from fire_detect_nn.models import FireClassifier

from streams.models.firewatch import FireWatch


@pytest.fixture(scope="module")
def random_firewatch_checkpoint(tmp_path_factory):
    """Build a randomly-initialized FireClassifier and save its state_dict."""
    tmp_path = tmp_path_factory.mktemp("firewatch")
    model = FireClassifier(backbone="densenet121", pretrained=False)
    ckpt = tmp_path / "test_firewatch.pt"
    torch.save(model.state_dict(), ckpt)
    return ckpt


def test_firewatch_backend_loads_checkpoint(random_firewatch_checkpoint):
    backend = FireWatch(
        model_path=str(random_firewatch_checkpoint),
        confidence_threshold=0.5,
        gradcam_every_n_fire_frames=1,
    )
    assert backend.model is not None
    assert backend.fire_transform is not None
    assert backend.device is not None
    assert backend.MODEL_TYPE == "firewatch"


def test_firewatch_predict_dict_shape(random_firewatch_checkpoint):
    backend = FireWatch(
        model_path=str(random_firewatch_checkpoint),
        confidence_threshold=0.5,
    )
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = backend.predict(frame)

    expected_keys = {
        "has_fire", "fire_probability", "detections", "timestamp",
        "model_type", "no_fire_probability",
    }
    assert expected_keys.issubset(result.keys()), f"missing: {expected_keys - result.keys()}"
    assert result["model_type"] == "firewatch"
    assert isinstance(result["has_fire"], bool)
    assert isinstance(result["detections"], list)
    assert 0.0 <= result["fire_probability"] <= 1.0
    assert 0.0 <= result["no_fire_probability"] <= 1.0


def test_firewatch_missing_checkpoint_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        FireWatch(
            model_path=str(tmp_path / "does_not_exist.pt"),
            confidence_threshold=0.5,
        )
