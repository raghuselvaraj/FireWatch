# FireWatch - Forest Fire Detection Pipeline

A real-time forest fire detection system using Kafka, machine learning, and AWS. Processes video streams to detect fires and stores annotated videos in S3.

## Architecture

```
Video Files → Kafka Producer → Kafka Topic (video-frames)
                                       ↓
                            Stream Processor (ML Inference)
                                       ↓
                    ┌──────────────────┴──────────────────┐
                    │                                     │
            Kafka Topic (fire-detections)    Kafka Topic (video-completions)
                    │                                     │
                    │                                     ↓
                    │                            S3 Upload Consumer
                    │                                     ↓
                    │                                 S3 Bucket
                    │
            (Detection results)
```

**Key Features:**
- **Horizontal Scaling**: Multiple producers and consumers can process videos in parallel
- **S3 Storage**: All overlayed videos are stored in S3 for scalable access
- **Partitioned Processing**: Kafka topics are partitioned for parallel processing
- **20-30 FPS**: Designed to process 20-30 frames per second per consumer

For detailed architecture diagrams, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

For scaling guide, see [docs/SCALING.md](docs/SCALING.md).

## Components

### 1. Video Producer (`producer/video_producer.py`)
- Reads video files and extracts frames
- Publishes frames to Kafka topic `video-frames`
- Encodes frames as base64 JPEG for efficient transmission

### 2. Fire Detection Stream (`python -m streams` — package at `streams/`)
- Python-based stream processor using kafka-python
- Consumes frames from `video-frames` topic
- Runs ML model inference on each frame
- Detects forest fires in real-time
- **Generates full annotated videos with heatmap overlays on fire detections**
- Publishes detection results to `fire-detections` topic
- Publishes video completion events to `video-completions` topic

### 3. S3 Upload Consumer (`consumer/s3_video_consumer.py`)
- Consumes video completion events from `video-completions` topic
- Uploads completed overlayed videos to S3 bucket
- Supports horizontal scaling (multiple consumers can process uploads in parallel)
- Videos are stored at: `s3://your-bucket/videos/{video_id}_with_heatmaps.mp4`
- Local files can be automatically deleted after S3 upload (configurable)

**Benefits of separate S3 consumer:**
- Independent scaling of video processing vs S3 uploads
- Better fault isolation (S3 upload failures don't affect ML processing)
- Multiple upload consumers can process uploads in parallel

## Setup

### Prerequisites

- Python 3.8+
- Apache Kafka (running locally or remote)
- AWS account with S3 bucket (for storing overlayed videos)
- Video files for processing

### Installation

1. Clone the repository and navigate to the project directory:
```bash
cd FireWatch
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies and fire-detect-nn:
```bash
# Install Python dependencies
pip install -r requirements.txt

# Install fire-detect-nn to site-packages (common Python libraries folder)
python3 scripts/install_fire_detect_nn.py
```

Alternatively, install as a package (which includes fire-detect-nn installation):
```bash
pip install -e .
```

4. Run unit tests (optional):
```bash
pytest
```

5. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your Kafka and AWS credentials (for S3)
```

### Environment Variables

Create a `.env` file with the following variables:

```env
# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_VIDEO_TOPIC=video-frames
KAFKA_DETECTIONS_TOPIC=fire-detections

# ML Model Configuration (fire-detect-nn is default)
ML_MODEL_TYPE=fire-detect-nn  # 'fire-detect-nn' (default) or 'ultralytics' (YOLOv8)
ML_MODEL_SOURCE=fire-detect-nn
CONFIDENCE_THRESHOLD=0.5  # Binary classification probability threshold (0.0-1.0)

# Alternative: YOLOv8 Configuration (if using ultralytics instead)
# ML_MODEL_TYPE=ultralytics
# ML_MODEL_NAME=touatikamel/yolov8s-forest-fire-detection
# ML_MODEL_PATH=models/fire_detection_model.pt
# IOU_THRESHOLD=0.45  # Intersection over Union threshold for NMS (YOLOv8 only)

# Video Output Configuration
CLIP_STORAGE_PATH=clips  # Temporary directory for annotated videos (before S3 upload)
CLIP_HEATMAP_OVERLAY_ALPHA=0.4  # Heatmap overlay transparency (0.0-1.0)

# S3 Configuration (required for video storage)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
S3_BUCKET=your-bucket-name
S3_DELETE_LOCAL_AFTER_UPLOAD=true  # Delete local files after S3 upload

# Scaling Configuration
KAFKA_VIDEO_TOPIC_PARTITIONS=6  # Number of partitions for horizontal scaling
KAFKA_DETECTIONS_TOPIC_PARTITIONS=6

```

### Download ML Model

After installing dependencies, download the forest fire detection model:

```bash
python3 scripts/install_fire_detect_nn.py
```

This clones the fire-detect-nn repository into your active Python environment's `site-packages` and downloads the pre-trained DenseNet121 weights.

## Usage

### Quick Start with Docker

The easiest way to get started is using Docker Compose:

```bash
# Start Kafka and Zookeeper
docker-compose up -d

# Create Kafka topics
./scripts/setup_kafka_topics.sh

# Or manually:
# docker exec -it firewatch-kafka-1 kafka-topics.sh --create --topic video-frames --bootstrap-server localhost:9092
# docker exec -it firewatch-kafka-1 kafka-topics.sh --create --topic fire-detections --bootstrap-server localhost:9092
```

### Manual Kafka Setup

If running Kafka locally without Docker:

```bash
# Start Zookeeper
bin/zookeeper-server-start.sh config/zookeeper.properties

# Start Kafka
bin/kafka-server-start.sh config/server.properties

# Create topics
./scripts/setup_kafka_topics.sh
# Or manually:
# bin/kafka-topics.sh --create --topic video-frames --bootstrap-server localhost:9092
# bin/kafka-topics.sh --create --topic fire-detections --bootstrap-server localhost:9092
```

### 2. Run the Pipeline

**Option A: Run all components together (recommended for testing)**

```bash
./scripts/run_full_test.sh path/to/your/video.mp4 [more_videos.mp4 ...]
```

This script automatically:
- Verifies Kafka is reachable (start it with `docker-compose up -d` first)
- Starts the fire detection stream processor (`--instances N` for multiple)
- Starts the S3 upload consumer (if `S3_BUCKET` is set in `.env`)
- Runs the producer against the videos you passed on the command line
- Streams a live per-video progress dashboard

Or process a specific video manually:
```bash
python3 producer/video_producer.py path/to/your/video.mp4 video_id_123
```

**Option B: Run components separately**

In separate terminals (run from project root directory):

```bash
# Terminal 1: Fire Detection Stream
python3 -m streams

# Terminal 2: S3 Upload Consumer
python3 consumer/s3_video_consumer.py

# Terminal 3: Produce Video Frames
python3 producer/video_producer.py path/to/your/video.mp4 video_id_123

# Terminal 4: View Detection Results
python3 scripts/kafka_inspect.py detections
```

## ML Model Integration

The implementation uses **fire-detect-nn** (DenseNet121) for forest fire detection with GradCAM-based visual identification.

### Model Details

- **Model**: fire-detect-nn from [tomasz-lewicki/fire-detect-nn](https://github.com/tomasz-lewicki/fire-detect-nn)
- **Architecture**: DenseNet121
- **Input Size**: 224x224 pixels
- **Type**: Binary classification (fire/no-fire)
- **Framework**: PyTorch
- **Features**: GradCAM heatmaps for visual fire region identification

### Setup

1. **Install fire-detect-nn to site-packages:**
   ```bash
   python3 scripts/install_fire_detect_nn.py
   ```

2. **Configure in `.env`:**
   ```env
   ML_MODEL_TYPE=fire-detect-nn
   ML_MODEL_SOURCE=fire-detect-nn
   CONFIDENCE_THRESHOLD=0.5  # Probability threshold (0.0-1.0)
   ```

### Alternative: YOLOv8 Models

The system also supports YOLOv8 models as an alternative. To use YOLOv8 instead of fire-detect-nn:

1. **Update `.env`:**
   ```env
   ML_MODEL_TYPE=ultralytics
   ML_MODEL_SOURCE=local  # or 'huggingface', 'roboflow'
   ML_MODEL_PATH=models/your_model.pt
   CONFIDENCE_THRESHOLD=0.25  # YOLOv8 confidence threshold
   IOU_THRESHOLD=0.45  # Non-maximum suppression threshold
   ```

**Note:** fire-detect-nn is recommended as it provides GradCAM heatmaps and is specifically trained for fire detection.

See [docs/MODELS.md](docs/MODELS.md) for detailed configuration of both fire-detect-nn and YOLOv8 backends.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System components, data flow, deployment diagrams
- [docs/MODELS.md](docs/MODELS.md) — Available models (fire-detect-nn, YOLOv8) and how to swap them
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — Local stack, running each component, pytest, debugging
- [docs/SCALING.md](docs/SCALING.md) — Horizontal scaling guide
- [docs/PERFORMANCE.md](docs/PERFORMANCE.md) — Throughput tuning, current optimizations, bottlenecks
- [infrastructure/docs/COST_OPTIMIZATION.md](infrastructure/docs/COST_OPTIMIZATION.md) — Cost optimization and MSK trade-offs
- [infrastructure/docs/MSK_SERVERLESS.md](infrastructure/docs/MSK_SERVERLESS.md) — MSK Serverless technical guide

## Project Structure

```
FireWatch/
├── producer/
│   ├── __init__.py
│   └── video_producer.py          # Kafka producer for video frames
├── streams/
│   ├── __init__.py                # re-exports the public surface
│   ├── __main__.py                # entrypoint: `python -m streams`
│   ├── stream.py                  # Kafka consumer loop + per-video state
│   ├── models/                    # FireDetectionModel + per-backend predictors
│   └── pipeline/                  # video_writer, overlay, progress, serialization
├── consumer/
│   ├── __init__.py
│   └── s3_video_consumer.py       # S3 upload consumer
├── scripts/
│   ├── install_fire_detect_nn.py  # Install fire-detect-nn to site-packages
│   ├── setup_kafka_topics.sh      # Create Kafka topics with partitions
│   ├── run_full_test.sh           # End-to-end pipeline runner (videos as args)
│   ├── test_with_videos.py        # Producer driver: one or more videos in parallel
│   ├── kafka_inspect.py           # status | messages | detections (Kafka inspector)
│   ├── clear_kafka_topics.sh      # Clear all Kafka topics
│   ├── reset_consumer_offsets.sh  # Reset consumer group offsets
│   ├── run_tests.sh               # Pytest entry point used by CI
│   └── stop_all.sh                # Kill leftover Python + docker-compose processes
├── docs/
│   ├── ARCHITECTURE.md            # Components, data flow, AWS topology
│   ├── MODELS.md                  # fire-detect-nn + YOLOv8 setup and tuning
│   ├── DEVELOPMENT.md             # Local stack, pytest, debugging
│   ├── SCALING.md                 # Horizontal scaling guide
│   └── PERFORMANCE.md             # Throughput tuning and bottlenecks
├── tests/                         # Pytest suite
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures (mock Kafka, sample frames)
│   ├── README.md                  # Test documentation
│   ├── test_utils.py
│   ├── test_video_producer.py
│   ├── test_fire_detection_stream.py
│   ├── test_s3_upload_consumer.py
│   ├── test_model_loading.py
│   ├── test_single_video_processing.py
│   ├── test_parallel_video_processing.py
│   └── test_video_finalization_concurrency.py
├── config.py                      # Configuration management
├── setup.py                       # Package setup (installs fire-detect-nn)
├── requirements.txt               # Python dependencies
├── pytest.ini                     # Pytest configuration
├── docker-compose.yml             # Local Kafka stack
├── .env.example                   # Environment variables template
├── README.md                      # This file
└── infrastructure/                # AWS CDK infrastructure
    ├── lib/                       # CDK construct definitions
    ├── bin/                       # CDK app entry point
    ├── Dockerfile.*               # Dockerfiles for services
    ├── README.md                  # Infrastructure overview
    └── DEPLOYMENT.md              # Detailed deployment guide
```

## Features

- **Real-time Processing**: Stream-based architecture for low-latency fire detection
- **Scalable**: Kafka enables horizontal scaling of producers, processors, and consumers
- **ML Integration**: fire-detect-nn (DenseNet121) for accurate fire detection with GradCAM heatmaps
- **Full Video Annotation**: Generates complete annotated videos with heatmap overlays on all fire detections
- **S3 Storage**: Stores annotated videos in S3 for scalable access and archival
- **Heatmap Visualization**: Uses GradCAM to visually highlight fire regions in detected frames
- **Metadata Preservation**: Tracks video IDs, frame numbers, timestamps, and detection details

## Notes

- This is a proof of concept. For production use, consider:
  - Error handling and retry logic
  - Monitoring and alerting
  - Model versioning
  - Batch processing for better throughput
  - Security and authentication
  - Resource optimization (frame sampling, compression)

## License

MIT
