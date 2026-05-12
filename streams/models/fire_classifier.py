"""DenseNet121 binary fire/no-fire classifier.

Independent reimplementation of the architecture used by both
:class:`~streams.models.fire_detect_nn.FireDetectNN` and
:class:`~streams.models.firewatch.FireWatch`. Kept in-project so we don't
depend on the unlicensed upstream ``fire_detect_nn.models.FireClassifier``.

State-dict layout matches the upstream class exactly — ``backbone.*`` keys
from ``torchvision.models.densenet121`` plus a ``backbone.classifier``
``Linear(1024, 1)`` head — so existing checkpoints load without conversion.
"""
from __future__ import annotations

import torch.nn as nn
import torchvision.models as tv_models


class FireClassifier(nn.Module):
    """DenseNet121 backbone + 1-unit Linear head + sigmoid.

    Args:
        backbone: Only ``"densenet121"`` is supported. The argument exists
            for call-site compatibility with the previous upstream class.
        pretrained: If True, init the backbone with torchvision's ImageNet1k
            weights (BSD-licensed). False = random init (for loading an
            existing state_dict on top).
    """

    def __init__(self, backbone: str = "densenet121", pretrained: bool = True):
        super().__init__()
        if backbone != "densenet121":
            raise NotImplementedError(
                f"FireClassifier only supports backbone='densenet121', got {backbone!r}"
            )
        if pretrained:
            self.backbone = tv_models.densenet121(weights=tv_models.DenseNet121_Weights.IMAGENET1K_V1)
        else:
            self.backbone = tv_models.densenet121(weights=None)
        # Replace the 1000-class ImageNet head with a single fire/no-fire logit.
        self.backbone.classifier = nn.Linear(in_features=1024, out_features=1, bias=True)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        x = self.backbone(x)
        x = self.sigmoid(x)
        return x
