"""Shared base for binary-classifier fire backends.

Both ``FireDetectNN`` (upstream pretrained) and ``FireWatch`` (trained in
``training/``) use the same ``FireClassifier`` architecture from the
fire-detect-nn package and the same input normalization. The only difference
is where the weights come from. This base class owns everything except that:
device selection, GradCAM cadence state, and the ``predict()`` method.

Subclasses override ``_load_weights(device) -> (model, transform)`` and set
``MODEL_TYPE``.
"""
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from streams.models.gradcam import compute_gradcam_heatmap


class FireClassifierPredictor:
    """Base class for binary fire/no-fire classifier backends.

    The output dict is shaped to match the YOLOv8 detector for downstream
    compatibility: a full-frame ``bbox`` covering the entire frame is
    synthesized when fire is detected, since the classifier doesn't produce
    bounding boxes natively.

    GradCAM cadence: if ``gradcam_every_n_fire_frames`` > 1, the heatmap is
    only recomputed every Nth consecutive positive frame and the previous
    heatmap is reused on the frames in between. Set to 1 for the legacy
    "compute on every positive frame" behavior.
    """

    MODEL_TYPE: str = "abstract"

    def __init__(self, confidence_threshold: float, gradcam_every_n_fire_frames: int = 1):
        self.confidence_threshold = confidence_threshold
        self.gradcam_every_n_fire_frames = max(1, gradcam_every_n_fire_frames)
        self._consecutive_fire_frames = 0
        self._last_heatmap: Optional[np.ndarray] = None
        self.device = self._select_device()
        self.model, self.fire_transform = self._load_weights(self.device)

    @staticmethod
    def _select_device():
        """Prefer CUDA, then Apple MPS, then CPU."""
        import torch

        if torch.cuda.is_available():
            print("  Using CUDA (NVIDIA GPU) for acceleration")
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            print("  Using MPS (Apple Silicon GPU) for acceleration")
            return torch.device("mps")
        print("  Using CPU (no GPU acceleration available)")
        return torch.device("cpu")

    def _load_weights(self, device) -> Tuple[Any, Any]:
        raise NotImplementedError("subclasses must implement _load_weights")

    def predict(self, frame: np.ndarray) -> Dict[str, Any]:
        """Classify a frame as fire / no-fire and (on positive) compute GradCAM.

        Args:
            frame: BGR numpy array straight from OpenCV.

        Returns:
            Dict with ``has_fire``, ``fire_probability``, ``detections``,
            ``timestamp``, ``model_type``, ``no_fire_probability``, and
            (when fire is detected) a ``heatmap`` 2D numpy array.
        """
        try:
            import torch
            from PIL import Image

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            input_tensor = self.fire_transform(pil_image).unsqueeze(0).to(self.device)

            # fp16 autocast on CUDA is gated behind ENABLE_AUTOCAST_CUDA because
            # at batch_size=1 the autocast context overhead actually slows the
            # forward pass down (verified: ~22% slower on T4 at batch_size=1).
            use_autocast = (
                self.device.type == "cuda"
                and os.getenv("ENABLE_AUTOCAST_CUDA", "0").lower() in ("1", "true", "yes")
            )
            with torch.no_grad():
                if use_autocast:
                    with torch.autocast(device_type="cuda", dtype=torch.float16):
                        output = self.model(input_tensor)
                else:
                    output = self.model(input_tensor)
                fire_prob = output[0].cpu().item()
                no_fire_prob = 1.0 - fire_prob

            has_fire = fire_prob >= self.confidence_threshold

            heatmap: Optional[np.ndarray] = None
            if has_fire:
                self._consecutive_fire_frames += 1
                position = (self._consecutive_fire_frames - 1) % self.gradcam_every_n_fire_frames
                if position == 0:
                    try:
                        new_heatmap = compute_gradcam_heatmap(
                            self.model, self.fire_transform, self.device, frame
                        )
                        if new_heatmap is not None:
                            self._last_heatmap = new_heatmap
                    except Exception:
                        pass
                heatmap = self._last_heatmap
            else:
                self._consecutive_fire_frames = 0
                self._last_heatmap = None

            detections = []
            if has_fire:
                h, w = frame.shape[:2]
                detections.append(
                    {
                        "bbox": [0, 0, w, h],
                        "confidence": fire_prob,
                        "class": "fire",
                        "class_id": 1,
                    }
                )

            return {
                "has_fire": bool(has_fire),
                "fire_probability": float(fire_prob) if has_fire else 0.0,
                "detections": detections,
                "timestamp": datetime.utcnow().isoformat(),
                "model_type": self.MODEL_TYPE,
                "no_fire_probability": float(no_fire_prob),
                "heatmap": heatmap,
            }

        except Exception as e:
            print(f"Error in {self.MODEL_TYPE} prediction: {e}")
            import traceback

            traceback.print_exc()
            return {
                "has_fire": False,
                "fire_probability": 0.0,
                "detections": [],
                "timestamp": datetime.utcnow().isoformat(),
                "model_type": self.MODEL_TYPE,
                "error": str(e),
            }
