"""Blend a 2D heatmap onto a BGR video frame."""
from typing import Optional

import cv2
import numpy as np

import config


def overlay_heatmap_on_frame(
    frame: np.ndarray,
    heatmap: Optional[np.ndarray],
    alpha: Optional[float] = None,
) -> np.ndarray:
    """Overlay a 2D heatmap on a BGR frame.

    Args:
        frame: Input frame (BGR format).
        heatmap: 2D heatmap array, or None (returns frame unchanged).
        alpha: Transparency of heatmap overlay (0.0-1.0). Defaults to
            ``config.CLIP_HEATMAP_OVERLAY_ALPHA``.

    Returns:
        Frame with the heatmap overlaid in JET colormap, or the original
        frame if ``heatmap`` is None.
    """
    if heatmap is None:
        return frame

    if alpha is None:
        alpha = config.CLIP_HEATMAP_OVERLAY_ALPHA

    h, w = frame.shape[:2]
    heatmap_resized = cv2.resize(heatmap, (w, h))

    # Normalize to 0-255
    heatmap_norm = (heatmap_resized - heatmap_resized.min()) / (
        heatmap_resized.max() - heatmap_resized.min() + 1e-8
    )
    heatmap_uint8 = (heatmap_norm * 255).astype(np.uint8)

    # JET colormap: blue → green → yellow → red (fire-like ramp)
    heatmap_colored = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_JET)
    return cv2.addWeighted(frame, 1.0 - alpha, heatmap_colored, alpha, 0)
