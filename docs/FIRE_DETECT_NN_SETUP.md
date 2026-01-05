# fire-detect-nn Model Setup

This project uses the fire-detect-nn model from [tomasz-lewicki/fire-detect-nn](https://github.com/tomasz-lewicki/fire-detect-nn) by importing it directly from the GitHub repository.

## Quick Setup

fire-detect-nn is automatically installed to your Python site-packages directory (common libraries folder) when you set up FireWatch.

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install fire-detect-nn to site-packages:**
   ```bash
   python3 scripts/install_fire_detect_nn.py
   ```
   
   This will:
   - Clone the fire-detect-nn repository to your Python site-packages directory
   - Download the pretrained weights
   - Make it available as a Python package (`import fire_detect_nn`)

   **Or install everything at once:**
   ```bash
   pip install -e .
   ```

3. **Update `.env`:**
   ```env
   ML_MODEL_TYPE=fire-detect-nn
   ML_MODEL_SOURCE=fire-detect-nn
   CONFIDENCE_THRESHOLD=0.5  # Probability threshold (0-1)
   ```

4. **Test the model:**
   ```bash
   python3 scripts/test_model_directly.py
   ```

## Configuration

The fire-detect-nn integration uses these configuration options (in `config.py` or `.env`):

- `ML_MODEL_TYPE=fire-detect-nn` - Use fire-detect-nn instead of Ultralytics
- `ML_MODEL_SOURCE=fire-detect-nn` - Source type
- `FIRE_DETECT_NN_DIR=fire-detect-nn` - Local directory (fallback, if not in site-packages)
- `FIRE_DETECT_NN_WEIGHTS=fire-detect-nn/weights/firedetect-densenet121-pretrained.pt` - Weights file path (fallback)
- `CONFIDENCE_THRESHOLD=0.5` - Detection threshold (0-1 for probability)

## Model Details

- **Architecture**: DenseNet121
- **Type**: Binary classification (fire/no-fire)
- **Input Size**: 224x224 pixels
- **Output**: Probability scores for fire and no-fire classes

## How It Works

The code imports fire-detect-nn as a Python package from site-packages:

1. The `install_fire_detect_nn.py` script clones the repository to site-packages and downloads weights
2. The `fire_detection_stream.py` imports `fire_detect_nn` as a regular Python package
3. Falls back to local directory if not found in site-packages (for backwards compatibility)
4. PyTorch's DenseNet121 model is loaded with the pretrained weights
5. Since it's a classification model (not object detection), it returns full-frame detections

**Location:** fire-detect-nn is installed to your Python environment's site-packages directory, making it available system-wide or within your virtual environment.
5. Results are converted to the standard format used by the pipeline

## Differences from YOLOv8

- **Classification vs Detection**: fire-detect-nn is a classification model, so it doesn't provide bounding boxes. The pipeline creates a full-frame detection when fire is detected.
- **Single Class**: Only detects fire/no-fire (binary), not multiple fire-related classes
- **Probability Output**: Returns probability scores rather than confidence scores

## Troubleshooting

### "fire-detect-nn not found" error

- Install fire-detect-nn: `python3 scripts/install_fire_detect_nn.py`
- This installs it to your Python site-packages directory
- Check installation: `python3 -c "import fire_detect_nn; print(fire_detect_nn.__file__)"`

### "PyTorch not installed" error

- Install PyTorch: `pip install torch torchvision`
- The requirements.txt should already include these

### "Weights file not found" error

- The install script should download weights automatically
- If missing, download manually: `wget https://dl.dropbox.com/s/6t17srif65vzqfn/firedetect-densenet121-pretrained.pt -O <site-packages>/fire_detect_nn/weights/firedetect-densenet121-pretrained.pt`
- Find site-packages: `python3 -c "import site; print(site.getsitepackages()[0])"`

### Model not detecting fires

- Check confidence threshold: Lower values (0.3-0.5) will detect more, higher values (0.7-0.9) will be more strict
- Verify the model is loaded correctly by checking startup logs
- Test with `python3 scripts/test_model_directly.py` to see raw probabilities

## References

- fire-detect-nn Repository: https://github.com/tomasz-lewicki/fire-detect-nn
- Pretrained Weights: https://dl.dropbox.com/s/6t17srif65vzqfn/firedetect-densenet121-pretrained.pt

