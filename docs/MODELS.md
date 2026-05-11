# Fire Detection Models

FireWatch supports two model backends, selected via the `ML_MODEL_TYPE` environment variable.

| `ML_MODEL_TYPE` | Backend | Strengths |
|---|---|---|
| `fire-detect-nn` (default) | DenseNet121 binary classifier from [tomasz-lewicki/fire-detect-nn](https://github.com/tomasz-lewicki/fire-detect-nn) | Pretrained for fire; provides GradCAM heatmaps for visual fire-region overlay. |
| `ultralytics` | YOLOv8 object detector via the [`ultralytics`](https://docs.ultralytics.com/) package | Provides bounding boxes; works with any YOLOv8 fire-trained checkpoint. |

> A third option, `firewatch` (our own trained checkpoint), is planned for Phase 4 of the refactor. See `docs/TRAINING.md` once added.

---

## fire-detect-nn (default)

### Install

```bash
pip install -r requirements.txt
python3 scripts/install_fire_detect_nn.py
```

The install script clones the upstream repo and copies it (plus the pretrained weights) into your active Python environment's `site-packages` so it's importable as `import fire_detect_nn`. Alternatively, `pip install -e .` runs the install script as part of the setup hook.

Verify:

```bash
python3 -c "import fire_detect_nn; print(fire_detect_nn.__file__)"
```

### Configure

In `.env`:

```env
ML_MODEL_TYPE=fire-detect-nn
ML_MODEL_SOURCE=fire-detect-nn
CONFIDENCE_THRESHOLD=0.5
```

- `CONFIDENCE_THRESHOLD` is the binary-classifier probability cutoff (0.0–1.0). Lower = more sensitive, higher = more conservative. `0.5` is the default; tune against a known-labeled clip set.
- `IOU_THRESHOLD` is **not used** by fire-detect-nn (it's a non-maximum-suppression knob; classifiers have nothing to suppress). The variable still exists in `config.py` for the YOLOv8 path.

### Model details

| Property | Value |
|---|---|
| Architecture | DenseNet121 backbone, sigmoid head |
| Task | Binary classification (fire vs no-fire) |
| Input | 224×224 RGB, custom normalization (mean 0.4005/0.3702/0.3419, std 0.2858/0.2749/0.2742) |
| Output | Single probability ∈ [0, 1] |
| Weights | `firedetect-densenet121-pretrained.pt` from upstream (Dropbox-hosted) |

The stream wraps the model output into a "full-frame detection" so downstream consumers receive a uniform message shape: `bbox = [0, 0, width, height]`, `class = "fire"`, `confidence = probability`.

### GradCAM heatmaps

On positive frames (probability ≥ `CONFIDENCE_THRESHOLD`) the stream computes a GradCAM heatmap over the DenseNet features and blends it onto the frame using `CLIP_HEATMAP_OVERLAY_ALPHA`. If GradCAM fails for any reason (hook not registered, OOM), the frame is still written to the output video — just without the overlay.

---

## YOLOv8 (`ultralytics`)

### Install

YOLOv8 ships with `ultralytics` in [requirements.txt](../requirements.txt), so no extra setup is required beyond providing a fire-trained checkpoint.

### Configure

In `.env`:

```env
ML_MODEL_TYPE=ultralytics
ML_MODEL_SOURCE=local         # 'local' or 'huggingface'
ML_MODEL_PATH=models/your_model.pt
ML_MODEL_NAME=touatikamel/yolov8s-forest-fire-detection  # only used if ML_MODEL_SOURCE=huggingface
CONFIDENCE_THRESHOLD=0.25
IOU_THRESHOLD=0.45
```

`ML_MODEL_SOURCE` accepts `local` (load `ML_MODEL_PATH` from disk) or `huggingface` (download by `ML_MODEL_NAME`). Other values fall through to the same code path and are not separately wired.

### Getting a fire-trained checkpoint

- **Hugging Face**: pre-trained models like `touatikamel/yolov8s-forest-fire-detection` work out of the box.
- **Roboflow Universe**: https://universe.roboflow.com (search "fire detection") publishes YOLO datasets and exported weights.
- **Train your own** with `ultralytics`:
  ```python
  from ultralytics import YOLO
  YOLO("yolov8s.pt").train(data="path/to/dataset.yaml", epochs=100, imgsz=640)
  ```

### Class filtering

YOLOv8 returns boxes for many object classes. The stream keeps boxes whose label matches any of `fire`, `smoke`, `flame`, `burn`, `wildfire` while excluding common false-positive labels (`fire hydrant`, `fire truck`, `extinguisher`, `alarm`, `station`, `engine`).

---

## Tuning the threshold

If you're getting too many false positives or missing real fires, change `CONFIDENCE_THRESHOLD` in `.env`:

- fire-detect-nn: 0.3–0.4 catches more fires (and more false positives); 0.6–0.7 is more conservative. Default 0.5.
- YOLOv8: 0.25 is the ultralytics default. Raise to ~0.4 if a particular model is noisy.

For repeatable comparison, run the same clip with several thresholds and inspect the published detections:

```bash
CONFIDENCE_THRESHOLD=0.3 python3 -m streams &
python3 scripts/test_with_videos.py path/to/known_fire.mp4
python3 scripts/kafka_inspect.py detections --limit 50
```

---

## Troubleshooting

### `fire-detect-nn not installed`

The install script writes to site-packages — re-run it after activating your virtualenv:

```bash
python3 scripts/install_fire_detect_nn.py
python3 -c "import fire_detect_nn; print(fire_detect_nn.__file__)"
```

### `Weights file not found`

If the install script's Dropbox download failed, fetch the weights manually and drop them next to the installed package:

```bash
WEIGHTS_DIR=$(python3 -c "import fire_detect_nn, pathlib; print(pathlib.Path(fire_detect_nn.__file__).parent / 'weights')")
mkdir -p "$WEIGHTS_DIR"
curl -L https://dl.dropbox.com/s/6t17srif65vzqfn/firedetect-densenet121-pretrained.pt \
  -o "$WEIGHTS_DIR/firedetect-densenet121-pretrained.pt"
```

### Model not detecting fires

- Lower `CONFIDENCE_THRESHOLD` (start at 0.3) and re-run a known-fire clip.
- Confirm the stream actually loaded the model: the startup log prints `Using fire-detect-nn from: ...` or `Loading model from local path: ...`.
- Inspect the raw detection messages: `python3 scripts/kafka_inspect.py detections`.

## References

- fire-detect-nn: https://github.com/tomasz-lewicki/fire-detect-nn
- Pretrained DenseNet121 weights: https://dl.dropbox.com/s/6t17srif65vzqfn/firedetect-densenet121-pretrained.pt
- Ultralytics YOLOv8 docs: https://docs.ultralytics.com
