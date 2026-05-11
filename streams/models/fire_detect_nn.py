"""Backend for the fire-detect-nn DenseNet121 binary classifier.

The upstream package is fetched into site-packages by
``scripts/install_fire_detect_nn.py``. This module assumes that import
``fire_detect_nn`` succeeds and that the pretrained weights file lives at
``<site-packages>/fire_detect_nn/weights/firedetect-densenet121-pretrained.pt``.
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np

from streams.models.gradcam import compute_gradcam_heatmap


class FireDetectNN:
    """DenseNet121 fire/no-fire classifier with optional GradCAM heatmap.

    The output dict is shaped to match the YOLOv8 detector for downstream
    compatibility: a full-frame ``bbox`` covering the entire frame is
    synthesized when fire is detected, since the classifier doesn't produce
    bounding boxes natively.

    GradCAM cadence: if ``gradcam_every_n_fire_frames`` > 1, the heatmap is
    only recomputed every Nth consecutive positive frame and the previous
    heatmap is reused on the frames in between. Set to 1 for the legacy
    "compute on every positive frame" behavior.
    """

    def __init__(self, confidence_threshold: float, gradcam_every_n_fire_frames: int = 1):
        self.confidence_threshold = confidence_threshold
        self.gradcam_every_n_fire_frames = max(1, gradcam_every_n_fire_frames)
        self._consecutive_fire_frames = 0
        self._last_heatmap: Optional[np.ndarray] = None
        self.model, self.device, self.fire_transform = self._load()

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

    @staticmethod
    def _load():
        try:
            import torch
            import fire_detect_nn
            from fire_detect_nn.models import FireClassifier
            from fire_detect_nn.datasets.combo import transform as fire_transform

            pkg_path = Path(fire_detect_nn.__file__).parent
            weights_path = pkg_path / "weights" / "firedetect-densenet121-pretrained.pt"
            print(f"Using fire-detect-nn from: {pkg_path}")

            if not weights_path.exists():
                raise FileNotFoundError(
                    f"fire-detect-nn weights not found: {weights_path}\n"
                    "Run: python3 scripts/install_fire_detect_nn.py to download weights"
                )

            print(f"Loading fire-detect-nn model from: {weights_path}")

            device = FireDetectNN._select_device()
            model = FireClassifier(backbone="densenet121", pretrained=False)
            state_dict = torch.load(weights_path, map_location=device)
            model.load_state_dict(state_dict)
            model.eval()
            model.to(device)

            print(f"✓ fire-detect-nn model loaded successfully on {device}")
            return model, device, fire_transform

        except ImportError as e:
            raise ImportError(
                "Required modules not found. Make sure fire-detect-nn is installed.\n"
                "Run: python3 scripts/install_fire_detect_nn.py\n"
                f"Original error: {e}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load fire-detect-nn model: {e}")

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

            # fp16 autocast on CUDA gives ~1.5-2x throughput for free; MPS
            # support is still flaky on torch 2.x and Apple's fp16 path silently
            # mishandles some torchvision ops, so we leave it as fp32 there.
            # CPU autocast exists but offers little speedup for this model size.
            use_autocast = self.device.type == "cuda"
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
                # Recompute the heatmap on the first positive after a non-fire
                # gap, and every Nth positive thereafter. Reuse otherwise.
                position = (self._consecutive_fire_frames - 1) % self.gradcam_every_n_fire_frames
                if position == 0:
                    try:
                        new_heatmap = compute_gradcam_heatmap(
                            self.model, self.fire_transform, self.device, frame
                        )
                        if new_heatmap is not None:
                            self._last_heatmap = new_heatmap
                    except Exception:
                        # GradCAM is optional; fall through with the cached heatmap.
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
                "model_type": "fire-detect-nn",
                "no_fire_probability": float(no_fire_prob),
                "heatmap": heatmap,
            }

        except Exception as e:
            print(f"Error in fire-detect-nn prediction: {e}")
            import traceback

            traceback.print_exc()
            return {
                "has_fire": False,
                "fire_probability": 0.0,
                "detections": [],
                "timestamp": datetime.utcnow().isoformat(),
                "model_type": "fire-detect-nn",
                "error": str(e),
            }
