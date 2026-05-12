"""Backend for the FireWatch in-house DenseNet121 binary classifier.

Loads ``models/firewatch-v{N}.pt`` produced by ``training/`` into our
in-project :class:`~streams.models.fire_classifier.FireClassifier`. Same
architecture and same input normalization as the legacy fire-detect-nn
backend — only the weights differ.
"""
from pathlib import Path
from typing import Any, Tuple

from streams.models.classifier_predictor import FireClassifierPredictor
from streams.models.fire_classifier import FireClassifier
from streams.models.preprocessing import build_inference_transform


class FireWatch(FireClassifierPredictor):
    """FireClassifier loaded from a FireWatch-trained checkpoint."""

    MODEL_TYPE = "firewatch"

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float,
        gradcam_every_n_fire_frames: int = 1,
    ):
        self.model_path = model_path
        super().__init__(confidence_threshold, gradcam_every_n_fire_frames)

    def _load_weights(self, device) -> Tuple[Any, Any]:
        try:
            import torch
        except ImportError as e:
            raise ImportError(f"torch required: {e}")

        weights_path = Path(self.model_path)
        if not weights_path.exists():
            raise FileNotFoundError(
                f"FireWatch weights not found: {weights_path}\n"
                "Train a model first: python3 -m training.train\n"
                "Then export: python3 -m training.export --checkpoint <run>/best.pt"
            )

        print(f"Loading FireWatch model from: {weights_path}")
        model = FireClassifier(backbone="densenet121", pretrained=False)
        state_dict = torch.load(weights_path, map_location=device)
        model.load_state_dict(state_dict)
        model.eval()
        model.to(device)
        print(f"✓ FireWatch model loaded successfully on {device}")

        return model, build_inference_transform()
