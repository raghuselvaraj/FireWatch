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
# Default: fire-detect-nn (DenseNet121) - recommended for fire detection with GradCAM heatmaps
# Alternative: ultralytics (YOLOv8) - set ML_MODEL_TYPE=ultralytics to use
ML_MODEL_TYPE = os.getenv("ML_MODEL_TYPE", "fire-detect-nn")  # 'ultralytics' or 'fire-detect-nn'
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "models/fire_detection_model.pt")
ML_MODEL_SOURCE = os.getenv("ML_MODEL_SOURCE", "fire-detect-nn")  # 'huggingface', 'local', 'roboflow', 'fire-detect-nn', or 'download'
ML_MODEL_NAME = os.getenv("ML_MODEL_NAME", "touatikamel/yolov8s-forest-fire-detection")  # Only used if ML_MODEL_TYPE=ultralytics
# Fire-Detect-NN Configuration (from https://github.com/tomasz-lewicki/fire-detect-nn)
FIRE_DETECT_NN_DIR = os.getenv("FIRE_DETECT_NN_DIR", "fire-detect-nn")  # Directory where repo is cloned
FIRE_DETECT_NN_WEIGHTS = os.getenv("FIRE_DETECT_NN_WEIGHTS", "fire-detect-nn/weights/firedetect-densenet121-pretrained.pt")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))  # For fire-detect-nn (binary classification probability)
IOU_THRESHOLD = float(os.getenv("IOU_THRESHOLD", "0.45"))  # Intersection over Union threshold (not used for classification models)

# Video Output Configuration
CLIP_STORAGE_PATH = os.getenv("CLIP_STORAGE_PATH", "clips")  # Output directory for annotated videos
CLIP_HEATMAP_OVERLAY_ALPHA = float(os.getenv("CLIP_HEATMAP_OVERLAY_ALPHA", "0.4"))  # Heatmap overlay transparency (0.0-1.0, higher = more visible)

# S3 Configuration (for storing overlayed videos)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_DELETE_LOCAL_AFTER_UPLOAD = os.getenv("S3_DELETE_LOCAL_AFTER_UPLOAD", "true").lower() == "true"  # Delete local files after S3 upload

# Note: Snowflake and Iceberg configurations removed - system now uses S3 for storage
