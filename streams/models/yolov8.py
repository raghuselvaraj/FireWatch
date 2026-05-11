"""Backend for Ultralytics YOLOv8 fire detectors.

Unlike fire-detect-nn this is an object detector — predictions come back as
bounding boxes labeled with class names. We filter for fire-related labels
(``fire``, ``smoke``, ``flame``, ``burn``, ``wildfire``) and exclude obvious
false positives (``fire hydrant``, ``fire truck``, ``extinguisher`` etc.).
"""
import os
from datetime import datetime
from typing import Any, Dict, Iterable

import cv2
import numpy as np
from ultralytics import YOLO


_FIRE_KEYWORDS = ("fire", "smoke", "flame", "burn", "wildfire")
_EXCLUDE_KEYWORDS = ("hydrant", "truck", "extinguisher", "alarm", "station", "engine")


def _is_fire_class(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in _FIRE_KEYWORDS) and not any(ex in n for ex in _EXCLUDE_KEYWORDS)


def _print_model_info(model: YOLO) -> None:
    """Log fire-related class names found in the loaded YOLO model. Quiet on failure."""
    try:
        if hasattr(model, "names") and model.names:
            classes = list(model.names.values())
            fire_classes = [c for c in classes if any(kw in c.lower() for kw in ("fire", "smoke", "flame", "burn"))]
            print(f"   Model classes: {len(classes)} total")
            if fire_classes:
                print(f"   ✓ Fire-related classes found: {fire_classes}")
            else:
                print("   ⚠️  No fire-related classes found in model!")
                print("   ⚠️  This model may not be suitable for fire detection")
                print(f"   ⚠️  First few classes: {classes[:10]}")
    except Exception:
        pass


class YOLOv8Detector:
    """Ultralytics YOLOv8 wrapper with fire-class filtering."""

    def __init__(self, model_path: str, model_source: str, model_name: str,
                 confidence_threshold: float, iou_threshold: float):
        self.model_path = model_path
        self.model_source = model_source
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.model = self._load()

    def _load(self) -> YOLO:
        """Load a YOLOv8 model from disk or Hugging Face, with fallbacks."""
        try:
            if self.model_source == "local" and os.path.exists(self.model_path):
                print(f"Loading model from local path: {self.model_path}")
                model = YOLO(self.model_path)
                _print_model_info(model)
                return model

            if self.model_source == "huggingface":
                print(f"Attempting to load from Hugging Face: {self.model_name}")
                try:
                    model = YOLO(self.model_name)
                    _print_model_info(model)
                    try:
                        os.makedirs(os.path.dirname(self.model_path) or "models", exist_ok=True)
                        model.save(self.model_path)
                        print(f"Model saved to: {self.model_path}")
                    except Exception:
                        pass
                    return model
                except Exception as hf_error:
                    print(f"⚠️  Could not load from Hugging Face: {hf_error}")
                    print(f"   Model '{self.model_name}' may not exist or be accessible")
            else:
                print(f"Attempting to download from Hugging Face: {self.model_name}")
                try:
                    model = YOLO(self.model_name)
                    _print_model_info(model)
                    os.makedirs(os.path.dirname(self.model_path) or "models", exist_ok=True)
                    model.save(self.model_path)
                    print(f"Model saved to: {self.model_path}")
                    return model
                except Exception as dl_error:
                    print(f"⚠️  Could not download model: {dl_error}")

            if os.path.exists(self.model_path):
                print(f"Using local model file: {self.model_path}")
                model = YOLO(self.model_path)
                _print_model_info(model)
                return model

            raise ValueError(
                "Could not load YOLOv8 model from any source.\n"
                f"  Tried: {self.model_path}, {self.model_name}\n"
                "  To fix:\n"
                "  1. Set ML_MODEL_TYPE=fire-detect-nn (recommended, default)\n"
                "  2. Or provide a valid fire detection YOLOv8 model\n"
                "  3. Set ML_MODEL_SOURCE=local and ML_MODEL_PATH to your model file"
            )

        except Exception as e:
            raise ValueError(
                f"Error loading YOLOv8 model: {e}\n"
                "  To fix:\n"
                "  1. Set ML_MODEL_TYPE=fire-detect-nn (recommended, default)\n"
                "  2. Or provide a valid fire detection YOLOv8 model\n"
                "  3. Set ML_MODEL_SOURCE=local and ML_MODEL_PATH to your model file"
            ) from e

    def predict(self, frame: np.ndarray) -> Dict[str, Any]:
        """Run YOLOv8 inference and filter boxes for fire classes."""
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Probe with a low confidence so we see candidate boxes; the final
            # threshold check below uses self.confidence_threshold for the
            # actual "is fire" decision.
            inference_conf = min(0.1, self.confidence_threshold)
            results = self.model.predict(
                frame_rgb,
                conf=inference_conf,
                iou=self.iou_threshold,
                verbose=False,
                imgsz=640,
            )

            detections = []
            max_confidence = 0.0
            has_fire = False

            for result in results:
                boxes = result.boxes
                if boxes is None or len(boxes) == 0:
                    continue
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    confidence = box.conf[0].cpu().item()
                    class_id = int(box.cls[0].cpu().item())
                    class_name = result.names[class_id] if hasattr(result, "names") else f"class_{class_id}"

                    if _is_fire_class(class_name) and confidence > self.confidence_threshold:
                        has_fire = True
                        max_confidence = max(max_confidence, confidence)
                        detections.append(
                            {
                                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                                "confidence": float(confidence),
                                "class": class_name,
                                "class_id": class_id,
                            }
                        )

            return {
                "has_fire": bool(has_fire),
                "fire_probability": float(max_confidence) if has_fire else 0.0,
                "detections": detections,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            print(f"Error during prediction: {e}")
            return {
                "has_fire": False,
                "fire_probability": 0.0,
                "detections": [],
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            }
