"""Fire-detection model backends.

The public surface is :class:`FireDetectionModel`, a thin dispatcher that
loads either :class:`~streams.models.fire_detect_nn.FireDetectNN` or
:class:`~streams.models.yolov8.YOLOv8Detector` based on the ``ML_MODEL_TYPE``
config value. Both backends implement the same ``predict(frame) -> dict``
contract.
"""
from streams.models.dispatcher import FireDetectionModel

__all__ = ["FireDetectionModel"]
