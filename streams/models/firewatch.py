"""Backend for the FireWatch in-house DenseNet121 binary classifier.

Architecturally identical to ``FireDetectNN`` — both load the same
``FireClassifier`` from the fire-detect-nn package — but the weights come from
``models/firewatch-v{N}.pt`` produced by ``training/`` rather than the upstream
pretrained checkpoint. The shared inference path lives in
:class:`~streams.models.classifier_predictor.FireClassifierPredictor`.
"""
from pathlib import Path
from typing import Any, Tuple

from streams.models.classifier_predictor import FireClassifierPredictor


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
            from fire_detect_nn.models import FireClassifier
            from fire_detect_nn.datasets.combo import transform as fire_transform
        except ImportError as e:
            raise ImportError(
                "fire-detect-nn package required for FireClassifier architecture.\n"
                "Run: python3 scripts/install_fire_detect_nn.py\n"
                f"Original error: {e}"
            )

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

        return model, fire_transform
