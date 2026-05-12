"""Input preprocessing for the FireClassifier-based backends.

Constants are empirical RGB statistics for the training distribution (not
copyrightable expression). Both inference backends and the training pipeline
import from here to guarantee identical normalization end-to-end.
"""
from __future__ import annotations

from torchvision import transforms


# Empirical RGB mean/std for the aerial fire imagery the upstream fire-detect-nn
# pretrained checkpoint was trained on. The FireWatch v1 checkpoint was also
# trained with these statistics for inference-time compatibility.
IMG_SHAPE = (224, 224)
RGB_MEAN = (0.4005, 0.3702, 0.3419)
RGB_STD = (0.2858, 0.2749, 0.2742)


def build_inference_transform():
    """Deterministic PIL → Tensor transform used by every inference backend."""
    return transforms.Compose(
        [
            transforms.Resize(IMG_SHAPE),
            transforms.ToTensor(),
            transforms.Normalize(mean=RGB_MEAN, std=RGB_STD),
        ]
    )
