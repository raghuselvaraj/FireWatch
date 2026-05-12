"""Minimal Modal-hosted FireWatch inference for Phase 4 verification.

Wraps `streams.models.firewatch.FireWatch` in a T4-GPU Modal class so the same
checkpoint that runs locally can be exercised against a cloud GPU end-to-end.
Image bakes the source tree and the v1 checkpoint so cold start = container
boot + one model.load_state_dict.

This is intentionally NOT the Phase 7 production app — `keep_warm=0`, no
batching, no `predict_batch`. Phase 7 will promote and extend it.

Usage:
    # one-off warm test (uses the local 'positive_fire.mp4' for a single frame)
    modal run .modal/firewatch_smoke.py

    # from a host script:
    from .modal.firewatch_smoke import FireWatchSmoke
    with modal.enable_output():
        prediction = FireWatchSmoke().predict_jpeg.remote(jpeg_bytes)
"""
from __future__ import annotations

from pathlib import Path

import modal

REPO_ROOT = Path(__file__).resolve().parent.parent

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")  # opencv-python-headless still needs libgl/libglib at import time
    .pip_install(
        "torch>=2.0.0",
        "torchvision>=0.15.0",
        "opencv-python-headless>=4.8.0",
        "numpy>=1.24.0",
        "Pillow>=10.0.0",
        "python-dotenv>=1.0.0",
    )
    # Bake source + weights so cold start doesn't depend on a mount round-trip.
    .add_local_file(str(REPO_ROOT / "config.py"), "/root/config.py", copy=True)
    .add_local_dir(str(REPO_ROOT / "streams"), "/root/streams", copy=True)
    .add_local_file(
        str(REPO_ROOT / "models" / "firewatch-v1.pt"),
        "/root/models/firewatch-v1.pt",
        copy=True,
    )
)

app = modal.App("firewatch-smoke", image=image)


@app.cls(gpu="T4", scaledown_window=120)
class FireWatchSmoke:
    """T4-GPU FireWatch wrapper. One container = one loaded model.

    `predict_jpeg` mirrors the local predict() contract; heatmap is returned as
    a raw 2D float32 numpy array (Modal serializes via cloudpickle, so dtype
    and shape survive the round-trip without manual encoding).
    """

    @modal.enter()
    def load_model(self):
        import sys
        import types

        # The image bakes our code at /root; make it importable.
        if "/root" not in sys.path:
            sys.path.insert(0, "/root")

        # `streams/__init__.py` imports the Kafka stream consumer at package
        # load time, which would force a kafka-python install into a Modal
        # container that has no use for it. Stub the module so the import
        # chain (`streams` → `streams.stream` → `kafka`) is satisfied. The
        # FireWatch class itself never touches kafka.
        for mod in ("kafka", "kafka.errors"):
            if mod not in sys.modules:
                stub = types.ModuleType(mod)
                stub.KafkaConsumer = object  # type: ignore[attr-defined]
                stub.KafkaProducer = object  # type: ignore[attr-defined]
                stub.KafkaError = Exception  # type: ignore[attr-defined]
                sys.modules[mod] = stub

        from streams.models.firewatch import FireWatch

        # GradCAM every fire frame on the smoke path — we want to see heatmaps
        # for visual inspection, not amortize cost.
        self.model = FireWatch(
            model_path="/root/models/firewatch-v1.pt",
            confidence_threshold=0.5,
            gradcam_every_n_fire_frames=1,
        )

    @modal.method()
    def predict_jpeg(self, jpeg_bytes: bytes) -> dict:
        """Decode JPEG bytes to a BGR frame and run prediction.

        Returns the canonical predict() dict. Heatmap (if present) is a
        float32 numpy array; everything else matches the local contract.
        """
        import cv2
        import numpy as np

        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return {
                "has_fire": False,
                "fire_probability": 0.0,
                "detections": [],
                "model_type": "firewatch",
                "error": "could not decode jpeg",
            }
        return self.model.predict(frame)


@app.local_entrypoint()
def main():
    """Warm-test entrypoint: encode a synthetic 224x224 frame and round-trip it."""
    import cv2
    import numpy as np

    # Solid-orange frame — should NOT trigger fire (the model needs texture).
    # The point of this entrypoint is just to confirm the container boots and
    # the call shape works end-to-end, not to test accuracy.
    test_frame = np.full((480, 640, 3), (0, 140, 255), dtype=np.uint8)
    ok, jpeg = cv2.imencode(".jpg", test_frame)
    assert ok, "failed to encode test frame"

    cls = FireWatchSmoke()
    result = cls.predict_jpeg.remote(jpeg.tobytes())
    print(f"has_fire={result.get('has_fire')} prob={result.get('fire_probability'):.4f}")
    print(f"model_type={result.get('model_type')}")
    if "heatmap" in result and result["heatmap"] is not None:
        print(f"heatmap shape={result['heatmap'].shape} dtype={result['heatmap'].dtype}")
