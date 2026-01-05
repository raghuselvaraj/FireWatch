"""
Test the model directly on a single frame to see what it detects.
"""
import sys
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ultralytics import YOLO
import config


def test_model_on_frame():
    """Test model on a single frame from a video."""
    print("="*70)
    print("Direct Model Test")
    print("="*70)
    
    # Load model
    print("\n1. Loading model...")
    try:
        if config.ML_MODEL_SOURCE == "local" and Path(config.ML_MODEL_PATH).exists():
            model = YOLO(config.ML_MODEL_PATH)
            print(f"   Loaded from: {config.ML_MODEL_PATH}")
        else:
            print(f"   Attempting to load: {config.ML_MODEL_NAME}")
            try:
                model = YOLO(config.ML_MODEL_NAME)
            except Exception as load_error:
                print(f"   Error loading model: {load_error}")
                print("   ⚠️  Cannot load YOLOv8 model. Consider using fire-detect-nn instead:")
                print("      Set ML_MODEL_TYPE=fire-detect-nn in .env")
                raise
    except Exception as e:
        print(f"   Error: {e}")
        print("   ⚠️  Cannot load model. Consider using fire-detect-nn instead:")
        print("      Set ML_MODEL_TYPE=fire-detect-nn in .env")
        raise
    
    # Show model info
    if hasattr(model, 'names'):
        classes = list(model.names.values())
        print(f"\n2. Model has {len(classes)} classes")
        print(f"   First 20 classes: {classes[:20]}")
        fire_classes = [c for c in classes if any(kw in c.lower() for kw in ['fire', 'smoke', 'flame'])]
        if fire_classes:
            print(f"   ✓ Fire-related classes: {fire_classes}")
        else:
            print(f"   ✗ No fire-related classes found")
    
    # Test on a video frame
    print(f"\n3. Testing on video frame...")
    test_video = Path("test_files/trail_cams/actual_fires/fire_test_1.mp4")
    
    if not test_video.exists():
        print(f"   ⚠️  Test video not found: {test_video}")
        print(f"   Creating a test image instead...")
        # Create a test image
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    else:
        cap = cv2.VideoCapture(str(test_video))
        ret, frame = cap.read()
        cap.release()
        if ret:
            test_image = frame
            print(f"   Loaded frame from: {test_video}")
        else:
            print(f"   Could not read frame, using test image")
            test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    
    # Convert to RGB
    if len(test_image.shape) == 3 and test_image.shape[2] == 3:
        test_image_rgb = cv2.cvtColor(test_image, cv2.COLOR_BGR2RGB)
    else:
        test_image_rgb = test_image
    
    # Test with different confidence thresholds
    print(f"\n4. Running inference with different thresholds...")
    
    for conf_thresh in [0.1, 0.25, 0.5]:
        print(f"\n   Testing with confidence threshold: {conf_thresh}")
        results = model.predict(
            test_image_rgb,
            conf=conf_thresh,
            iou=config.IOU_THRESHOLD,
            verbose=False,
            imgsz=640
        )
        
        all_detections = []
        for result in results:
            if result.boxes is not None and len(result.boxes) > 0:
                for box in result.boxes:
                    conf = float(box.conf[0].cpu().numpy())
                    class_id = int(box.cls[0].cpu().numpy())
                    class_name = result.names[class_id] if hasattr(result, 'names') else f"class_{class_id}"
                    all_detections.append((class_name, conf))
        
        if all_detections:
            print(f"      Found {len(all_detections)} detections:")
            for cls, conf in sorted(all_detections, key=lambda x: x[1], reverse=True)[:10]:
                print(f"        - {cls}: {conf:.2%}")
        else:
            print(f"      No detections")
    
    # Check fire detection logic
    print(f"\n5. Testing fire detection logic...")
    results = model.predict(
        test_image_rgb,
        conf=0.1,  # Low threshold to see all detections
        iou=config.IOU_THRESHOLD,
        verbose=False,
        imgsz=640
    )
    
    fire_keywords = ['fire', 'smoke', 'flame', 'burn', 'wildfire']
    exclude_keywords = ['hydrant', 'truck', 'extinguisher', 'alarm', 'station', 'engine']
    
    fire_detections = []
    for result in results:
        if result.boxes is not None and len(result.boxes) > 0:
            for box in result.boxes:
                conf = float(box.conf[0].cpu().numpy())
                class_id = int(box.cls[0].cpu().numpy())
                class_name = result.names[class_id] if hasattr(result, 'names') else f"class_{class_id}"
                
                class_lower = class_name.lower()
                is_fire_class = any(kw in class_lower for kw in fire_keywords)
                is_excluded = any(exclude in class_lower for exclude in exclude_keywords)
                
                if is_fire_class and not is_excluded:
                    fire_detections.append((class_name, conf))
    
    if fire_detections:
        print(f"   ✓ Found {len(fire_detections)} fire-related detections:")
        for cls, conf in fire_detections:
            print(f"     - {cls}: {conf:.2%}")
    else:
        print(f"   ✗ No fire-related detections found")
        print(f"   This confirms the model doesn't have fire classes")
    
    print(f"\n{'='*70}")
    print("Summary:")
    print(f"{'='*70}")
    print(f"Current confidence threshold: {config.CONFIDENCE_THRESHOLD}")
    print(f"If model has no fire classes, no fires will be detected regardless of threshold.")
    print(f"See docs/MODEL_SETUP.md for how to get a fire detection model.")


if __name__ == "__main__":
    test_model_on_frame()

