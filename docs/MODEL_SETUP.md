# Fire Detection Model Setup

## Default Model: fire-detect-nn

The system uses **fire-detect-nn** (DenseNet121) as the default model for forest fire detection. This model provides:
- Binary classification (fire/no-fire)
- GradCAM heatmaps for visual fire region identification
- High accuracy on forest fire detection

### Quick Setup

1. **Clone repository and download weights:**
   ```bash
   python3 scripts/install_fire_detect_nn.py
   ```

2. **Configure in `.env`:**
   ```env
   ML_MODEL_TYPE=fire-detect-nn
   ML_MODEL_SOURCE=fire-detect-nn
   CONFIDENCE_THRESHOLD=0.5  # Probability threshold (0.0-1.0)
   ```

See `FIRE_DETECT_NN_SETUP.md` for detailed setup instructions.

## Alternative: YOLOv8 Models

If you prefer to use YOLOv8 models instead, you have a few options:

#### A. Find a Working Model

Search for fire detection models:
- GitHub: Search "yolov8 fire detection"
- Roboflow Universe: https://universe.roboflow.com (search "fire detection")
- Papers with Code: https://paperswithcode.com

#### B. Train Your Own Model

1. **Collect Dataset:**
   - Gather images/videos with fires
   - Gather images/videos without fires
   - Use tools like Roboflow or LabelImg for annotation

2. **Train with Ultralytics:**
   ```python
   from ultralytics import YOLO
   
   # Load base model
   model = YOLO('yolov8s.pt')
   
   # Train on your dataset
   model.train(data='path/to/your/dataset.yaml', epochs=100, imgsz=640)
   
   # Save trained model
   model.save('models/fire_detection_model.pt')
   ```

3. **Configure:**
   ```env
   ML_MODEL_SOURCE=local
   ML_MODEL_PATH=models/fire_detection_model.pt
   ```

## Adjusting Confidence Threshold

If you're getting false positives or missing detections, adjust the confidence threshold:

```env
# In .env file
CONFIDENCE_THRESHOLD=0.5  # Increase to reduce false positives, decrease to catch more fires
```

For fire-detect-nn:
- Lower threshold (0.3-0.4): More sensitive, may catch more fires but also false positives
- Higher threshold (0.6-0.7): More conservative, fewer false positives but may miss some fires
- Default (0.5): Balanced approach

## Verification

After setting up a model, verify it's working:

```bash
# Check what model is loaded
python3 streams/fire_detection_stream.py
# Look for: "Using fire-detect-nn model" or "Using Ultralytics YOLOv8 model"

# Test with your videos
python3 scripts/test_with_videos.py

# View results
python3 scripts/view_detections.py -l 10
```

## Recommended Approach

For a production system, we recommend:

1. **Use fire-detect-nn** as the default model (already configured)
2. **Fine-tune** on your specific data if needed (forest environments, camera angles, etc.)
3. **Validate** on test videos with known fire/no-fire labels
4. **Adjust thresholds** based on validation results

