"""Backend for the fire-detect-nn DenseNet121 binary classifier.

The upstream package is fetched into site-packages by
``scripts/install_fire_detect_nn.py``. This module assumes that import
``fire_detect_nn`` succeeds and that the pretrained weights file lives at
``<site-packages>/fire_detect_nn/weights/firedetect-densenet121-pretrained.pt``.
"""
from pathlib import Path
from typing import Any, Tuple

from streams.models.classifier_predictor import FireClassifierPredictor


class FireDetectNN(FireClassifierPredictor):
    """DenseNet121 fire/no-fire classifier loaded from upstream pretrained weights."""

    MODEL_TYPE = "fire-detect-nn"

    def _load_weights(self, device) -> Tuple[Any, Any]:
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

            model = FireClassifier(backbone="densenet121", pretrained=False)
            state_dict = torch.load(weights_path, map_location=device)
            model.load_state_dict(state_dict)
            model.eval()
            model.to(device)

            print(f"✓ fire-detect-nn model loaded successfully on {device}")
            return model, fire_transform

        except ImportError as e:
            raise ImportError(
                "Required modules not found. Make sure fire-detect-nn is installed.\n"
                "Run: python3 scripts/install_fire_detect_nn.py\n"
                f"Original error: {e}"
            )
        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to load fire-detect-nn model: {e}")
