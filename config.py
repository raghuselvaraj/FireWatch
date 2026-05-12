"""Configuration settings for FireWatch Kafka pipeline."""
import os
from dotenv import load_dotenv

load_dotenv()

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_VIDEO_TOPIC = os.getenv("KAFKA_VIDEO_TOPIC", "video-frames")
KAFKA_DETECTIONS_TOPIC = os.getenv("KAFKA_DETECTIONS_TOPIC", "fire-detections")
KAFKA_VIDEO_COMPLETIONS_TOPIC = os.getenv("KAFKA_VIDEO_COMPLETIONS_TOPIC", "video-completions")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "firewatch-consumer-group")
# Scaling Configuration - Set partition counts for horizontal scaling
KAFKA_VIDEO_TOPIC_PARTITIONS = int(os.getenv("KAFKA_VIDEO_TOPIC_PARTITIONS", "6"))  # Partitions for horizontal scaling
KAFKA_DETECTIONS_TOPIC_PARTITIONS = int(os.getenv("KAFKA_DETECTIONS_TOPIC_PARTITIONS", "6"))
KAFKA_VIDEO_COMPLETIONS_TOPIC_PARTITIONS = int(os.getenv("KAFKA_VIDEO_COMPLETIONS_TOPIC_PARTITIONS", "3"))

# Video Processing Configuration
FRAME_EXTRACTION_INTERVAL = int(os.getenv("FRAME_EXTRACTION_INTERVAL", "1"))  # Extract every Nth frame
FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", "640"))
FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", "480"))

# ML Model Configuration
# Supported ML_MODEL_TYPE values:
#   'fire-detect-nn' (default) — upstream pretrained DenseNet121 with GradCAM
#   'ultralytics'              — YOLOv8 (bounding-box detector)
#   'firewatch'                — DenseNet121 trained in-house via `training/` (see docs/TRAINING.md)
ML_MODEL_TYPE = os.getenv("ML_MODEL_TYPE", "fire-detect-nn")
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "models/fire_detection_model.pt")
ML_MODEL_SOURCE = os.getenv("ML_MODEL_SOURCE", "fire-detect-nn")  # 'huggingface', 'local', 'roboflow', 'fire-detect-nn', or 'download'
ML_MODEL_NAME = os.getenv("ML_MODEL_NAME", "touatikamel/yolov8s-forest-fire-detection")  # Only used if ML_MODEL_TYPE=ultralytics
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))  # Binary probability threshold (fire-detect-nn/firewatch) or YOLOv8 confidence
IOU_THRESHOLD = float(os.getenv("IOU_THRESHOLD", "0.45"))  # NMS IoU threshold (YOLOv8 only; ignored for classifier backends)

# Path to the FireWatch-trained checkpoint. Only used when ML_MODEL_TYPE=firewatch.
# Produced by `python -m training.export --checkpoint <run>/best.pt`.
FIREWATCH_MODEL_PATH = os.getenv("FIREWATCH_MODEL_PATH", "models/firewatch-v1.pt")

# Video Output Configuration
CLIP_STORAGE_PATH = os.getenv("CLIP_STORAGE_PATH", "clips")  # Output directory for annotated videos
CLIP_HEATMAP_OVERLAY_ALPHA = float(os.getenv("CLIP_HEATMAP_OVERLAY_ALPHA", "0.4"))  # Heatmap overlay transparency (0.0-1.0, higher = more visible)

# S3 Configuration (for storing overlayed videos)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_DELETE_LOCAL_AFTER_UPLOAD = os.getenv("S3_DELETE_LOCAL_AFTER_UPLOAD", "true").lower() == "true"  # Delete local files after S3 upload

# ---------- Phase 3 — performance & latency knobs ----------
# Offset commit cadence. The consumer commits after either condition fires —
# whichever comes first. The interval guard means a short video that doesn't
# reach the N-message threshold still gets its tail committed, so the
# run_full_test.sh "is the topic empty?" check completes naturally.
COMMIT_EVERY_N_MESSAGES = int(os.getenv("COMMIT_EVERY_N_MESSAGES", "250"))
COMMIT_INTERVAL_SECONDS = float(os.getenv("COMMIT_INTERVAL_SECONDS", "5.0"))

# Compute GradCAM only on every Nth consecutive positive (fire) frame, reusing
# the last heatmap for the frames in between. Consecutive fire frames tend to
# share spatial structure, so this is a near-lossless visual change that
# halves+ the expensive backward-pass cost on positive-heavy clips. Set to 1
# to disable (compute on every positive frame).
GRADCAM_EVERY_N_FIRE_FRAMES = int(os.getenv("GRADCAM_EVERY_N_FIRE_FRAMES", "5"))

# Run inference on every Nth frame. Skipped frames still get written to the
# output video — they just reuse the previous frame's detection state (no fire
# detected, no heatmap). Set to 1 to run inference on every frame.
INFERENCE_EVERY_N_FRAMES = int(os.getenv("INFERENCE_EVERY_N_FRAMES", "1"))

# Frame transport: 'msgpack' sends raw JPEG bytes inside msgpack (~33% smaller
# on the wire and ~5x faster decode vs base64-in-JSON). 'base64-json' is the
# legacy format. Producer and stream MUST agree on this setting.
FRAME_TRANSPORT = os.getenv("FRAME_TRANSPORT", "msgpack")
