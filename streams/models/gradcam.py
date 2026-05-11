"""GradCAM heatmap computation for the fire-detect-nn DenseNet121 classifier.

The procedure here matches what the original ``_compute_gradcam_heatmap``
did inline: register forward + backward hooks on the backbone's ``features``
layer, run a forward + backward pass over the input frame, then collapse
the channel-wise gradient-weighted activations into a 2D heatmap.

The hook-toggle dance (``model.train()`` → backward → ``model.eval()``)
is preserved here for behavior-parity with Phase 1. Phase 3 will replace
this with an eval-safe variant using ``torch.enable_grad()`` and the modern
``register_full_backward_hook`` API.
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
    try:
        import torch
        from PIL import Image

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(frame_rgb)
        input_tensor = fire_transform(pil_image).unsqueeze(0).to(device)
        input_tensor.requires_grad = True

        activations: Optional[Any] = None
        gradients: Optional[Any] = None

        def forward_hook(_module, _input, output):
            nonlocal activations
            activations = output

        def backward_hook(_module, _grad_input, grad_output):
            nonlocal gradients
            if grad_output[0] is not None:
                gradients = grad_output[0]

        hook_handle = None
        grad_handle = None
        if hasattr(model.backbone, "features"):
            features_layer = model.backbone.features
            hook_handle = features_layer.register_forward_hook(forward_hook)
            grad_handle = features_layer.register_backward_hook(backward_hook)

        try:
            model.train()  # temporarily enable grad-friendly mode
            output = model(input_tensor)
            fire_score = output[0]

            model.zero_grad()
            fire_score.backward(retain_graph=False)
        finally:
            model.eval()

        if activations is None or gradients is None:
            if hook_handle is not None:
                hook_handle.remove()
            if grad_handle is not None:
                grad_handle.remove()
            return None

        pooled_gradients = torch.mean(gradients, dim=[0, 2, 3], keepdim=True)
        weighted_activations = activations * pooled_gradients
        heatmap = torch.mean(weighted_activations, dim=1, keepdim=False)
        heatmap = heatmap[0].cpu().detach().numpy()
        heatmap = np.maximum(heatmap, 0)
        if heatmap.max() > 0:
            heatmap = heatmap / heatmap.max()

        if hook_handle is not None:
            hook_handle.remove()
        if grad_handle is not None:
            grad_handle.remove()
        return heatmap

    except Exception:
        # GradCAM is optional — frame is still written without the overlay.
        try:
            model.eval()
        except Exception:
            pass
        return None
