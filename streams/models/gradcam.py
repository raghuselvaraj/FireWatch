"""Eval-safe GradCAM heatmap computation for the fire-detect-nn DenseNet121.

The pre-Phase-3 implementation toggled ``model.train()`` around the backward
pass to get gradients flowing — which silently changes BatchNorm and Dropout
behavior across the forward pass, distorting the very activations GradCAM is
trying to weigh. This version keeps the model in eval mode throughout and
just enables grad on the input tensor via ``torch.enable_grad()``.

Also swaps the deprecated ``register_backward_hook`` for the supported
``register_full_backward_hook`` (the old hook silently misbehaves with
``in-place`` ops in some torchvision releases).
"""
from typing import Any, Optional

import cv2
import numpy as np


def compute_gradcam_heatmap(model: Any, fire_transform: Any, device: Any, frame: np.ndarray) -> Optional[np.ndarray]:
    """Compute a 2D GradCAM heatmap for a frame.

    Args:
        model: A loaded ``FireClassifier`` (DenseNet121 backbone + sigmoid head).
        fire_transform: The ``torchvision`` transform that normalizes a PIL
            image to the tensor shape the model expects.
        device: The ``torch.device`` the model lives on.
        frame: Input frame as numpy array in BGR format.

    Returns:
        A 2D heatmap (channels × height × width collapsed to height × width)
        normalized to [0, 1], or ``None`` if hooks failed to register or the
        backward pass produced no gradients.
    """
    if not hasattr(model, "backbone") or not hasattr(model.backbone, "features"):
        return None

    try:
        import torch
        from PIL import Image
    except Exception:
        return None

    activations: Optional[Any] = None
    gradients: Optional[Any] = None

    def forward_hook(_module, _input, output):
        nonlocal activations
        activations = output

    def full_backward_hook(_module, _grad_input, grad_output):
        nonlocal gradients
        if grad_output and grad_output[0] is not None:
            gradients = grad_output[0]

    features_layer = model.backbone.features
    hook_handle = features_layer.register_forward_hook(forward_hook)
    grad_handle = features_layer.register_full_backward_hook(full_backward_hook)

    try:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(frame_rgb)
        input_tensor = fire_transform(pil_image).unsqueeze(0).to(device)
        # Enable grad just on the input — model parameters stay frozen and
        # BatchNorm/Dropout stay in their eval-mode configuration, which is
        # critical for GradCAM to reflect the actual deployed model's behavior.
        input_tensor.requires_grad_(True)

        with torch.enable_grad():
            output = model(input_tensor)
            fire_score = output[0]
            model.zero_grad(set_to_none=True)
            fire_score.backward(retain_graph=False)

        if activations is None or gradients is None:
            return None

        pooled_gradients = torch.mean(gradients, dim=[0, 2, 3], keepdim=True)
        weighted_activations = activations * pooled_gradients
        heatmap = torch.mean(weighted_activations, dim=1, keepdim=False)
        heatmap = heatmap[0].cpu().detach().numpy()
        heatmap = np.maximum(heatmap, 0)
        if heatmap.max() > 0:
            heatmap = heatmap / heatmap.max()
        return heatmap

    except Exception:
        return None
    finally:
        hook_handle.remove()
        grad_handle.remove()
