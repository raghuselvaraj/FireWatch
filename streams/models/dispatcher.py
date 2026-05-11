"""Unified ``FireDetectionModel`` that dispatches to a backend.

Loads either :class:`~streams.models.fire_detect_nn.FireDetectNN` or
:class:`~streams.models.yolov8.YOLOv8Detector` depending on ``ML_MODEL_TYPE``
(and the legacy ``ML_MODEL_SOURCE`` alias). The dispatcher itself owns the
config plumbing so the backends stay decoupled from the env.
"""
import warnings
from typing import Any, Dict, Optional

import numpy as np

import config

# Suppress noisy library warnings while we're holding the model.
warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")
warnings.filterwarnings("ignore", message=".*x265.*")


# Pre-check that fire-detect-nn is importable when configured. This early
# warning is helpful at startup; the actual import still happens lazily inside
# the backend's loader.
FIRE_DETECT_NN_AVAILABLE = False
if config.ML_MODEL_TYPE == "fire-detect-nn" or config.ML_MODEL_SOURCE == "fire-detect-nn":
    try:
        import fire_detect_nn  # noqa: F401

        FIRE_DETECT_NN_AVAILABLE = True
        print("✓ fire-detect-nn found in site-packages")
    except ImportError:
        print("⚠️  fire-detect-nn not installed. Run: python3 scripts/install_fire_detect_nn.py")


class FireDetectionModel:
    """Top-level model facade.

    Reads its configuration from :mod:`config` and constructs the appropriate
    backend. Exposes ``predict(frame) -> dict`` (matching either backend) and
    keeps the same public attributes the old monolith had: ``model``,
    ``device`` (fire-detect-nn only), ``fire_transform`` (ditto),
    ``confidence_threshold``, ``iou_threshold``, ``use_fire_detect_nn``.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or config.ML_MODEL_PATH
        self.confidence_threshold = config.CONFIDENCE_THRESHOLD
        self.iou_threshold = config.IOU_THRESHOLD
        self.model_source = config.ML_MODEL_SOURCE
        self.model_name = config.ML_MODEL_NAME
        self.model_type = config.ML_MODEL_TYPE
        self.use_fire_detect_nn = (
            self.model_type == "fire-detect-nn" or self.model_source == "fire-detect-nn"
        )

        if self.use_fire_detect_nn:
            from streams.models.fire_detect_nn import FireDetectNN

            self._backend = FireDetectNN(confidence_threshold=self.confidence_threshold)
            self.model = self._backend.model
            self.device = self._backend.device
            self.fire_transform = self._backend.fire_transform
            print("fire-detect-nn model initialized (DenseNet121)")
        else:
            from streams.models.yolov8 import YOLOv8Detector

            self._backend = YOLOv8Detector(
                model_path=self.model_path,
                model_source=self.model_source,
                model_name=self.model_name,
                confidence_threshold=self.confidence_threshold,
                iou_threshold=self.iou_threshold,
            )
            self.model = self._backend.model
            print(f"Fire detection model initialized: {self.model_name}")

        print(
            f"Confidence threshold: {self.confidence_threshold}, "
            f"IOU threshold: {self.iou_threshold}"
        )

    def predict(self, frame: np.ndarray) -> Dict[str, Any]:
        """Dispatch to the configured backend."""
        return self._backend.predict(frame)
