"""Build a FireClassifier for training.

The upstream ``FireClassifier`` applies sigmoid in ``forward()`` — fine for
inference but numerically unstable for BCE loss. We swap the sigmoid out for
``nn.Identity`` so training can use ``BCEWithLogitsLoss``, then ``export.py``
re-attaches the real sigmoid before writing the deployable checkpoint. The
state_dict is identical either way (sigmoid has no parameters).
"""
from __future__ import annotations

import torch.nn as nn
from fire_detect_nn.models import FireClassifier


def build_model(pretrained: bool = True, backbone: str = "densenet121") -> FireClassifier:
    """Return a ``FireClassifier`` configured for logit-mode training.

    Args:
        pretrained: If True, init the DenseNet121 backbone with ImageNet weights.
            Should be True for from-scratch training; False when loading our
            own state_dict afterwards.
        backbone: Passed to ``FireClassifier``. Only ``densenet121`` is
            supported end-to-end (the inference path expects DenseNet features).
    """
    model = FireClassifier(backbone=backbone, pretrained=pretrained)
    # Strip the sigmoid so the model emits logits — required for BCEWithLogitsLoss.
    model.sigmoid = nn.Identity()
    return model


def restore_sigmoid(model: FireClassifier) -> FireClassifier:
    """Re-attach ``nn.Sigmoid`` for inference. Mirror of ``build_model``."""
    import torch.nn as nn

    model.sigmoid = nn.Sigmoid()
    return model
