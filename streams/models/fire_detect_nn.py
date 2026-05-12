"""Backend for the legacy fire-detect-nn DenseNet121 pretrained weights.

Loads the upstream pretrained `.pt` file fetched by
``scripts/install_fire_detect_nn.py`` into our in-project
:class:`~streams.models.fire_classifier.FireClassifier` (which has the same
architecture). The fire-detect-nn Python package is not imported — only its
weights file is consumed.

For new deployments prefer ``ML_MODEL_TYPE=firewatch`` with the in-house
trained checkpoint (see docs/TRAINING.md). This backend is kept as an
opt-in for users with the upstream weights already installed.
"""
from pathlib import Path
from typing import Any, Tuple

from streams.models.classifier_predictor import FireClassifierPredictor
from streams.models.fire_classifier import FireClassifier
from streams.models.preprocessing import build_inference_transform


class FireDetectNN(FireClassifierPredictor):
    """DenseNet121 fire/no-fire classifier loaded from upstream pretrained weights."""

    MODEL_TYPE = "fire-detect-nn"

    def _load_weights(self, device) -> Tuple[Any, Any]:
        try:
            import torch
        except ImportError as e:
            raise ImportError(f"torch required: {e}")

        # The install script puts the upstream package + weights file under
        # site-packages/fire_detect_nn/weights/. We only need the weights file
        # — locate it without importing the package.
        try:
            import importlib.util

            spec = importlib.util.find_spec("fire_detect_nn")
            if spec is None or spec.origin is None:
                raise FileNotFoundError("fire_detect_nn package directory not found")
            pkg_path = Path(spec.origin).parent
        except (ImportError, FileNotFoundError):
            raise FileNotFoundError(
                "Could not locate fire-detect-nn weights directory.\n"
                "Run: python3 scripts/install_fire_detect_nn.py to install it,\n"
                "or use ML_MODEL_TYPE=firewatch with your own trained checkpoint."
            )

        weights_path = pkg_path / "weights" / "firedetect-densenet121-pretrained.pt"
        if not weights_path.exists():
            raise FileNotFoundError(
                f"fire-detect-nn weights not found: {weights_path}\n"
                "Run: python3 scripts/install_fire_detect_nn.py to download weights"
            )

        print(f"Loading fire-detect-nn weights from: {weights_path}")
        model = FireClassifier(backbone="densenet121", pretrained=False)
        state_dict = torch.load(weights_path, map_location=device)
        model.load_state_dict(state_dict)
        model.eval()
        model.to(device)
        print(f"✓ fire-detect-nn model loaded successfully on {device}")

        return model, build_inference_transform()
