# Local Development & Testing

Run the full FireWatch stack on your machine with Docker Compose plus a handful of Python processes. Same code as the AWS deployment; only the Kafka infrastructure differs.

## TL;DR

```bash
docker-compose up -d                                       # 1. Start local Kafka
./scripts/setup_kafka_topics.sh                            # 2. Create topics
./scripts/run_full_test.sh path/to/some_video.mp4          # 3. Run the whole pipeline against your video
```

Annotated MP4s land in `clips/`. If `S3_BUCKET` is set, they're also uploaded to S3.

---

## What `docker-compose up -d` gives you

| Service | Port | Notes |
|---|---|---|
| Zookeeper | 2181 | Kafka metadata |
| Kafka broker | 9092 | Single broker, no replication |
| Kafka UI | http://localhost:8081 | Browse topics, messages, consumer groups |

The `setup_kafka_topics.sh` script creates:

| Topic | Partitions |
|---|---|
| `video-frames` | 6 |
| `fire-detections` | 6 |
| `video-completions` | 3 |

## What `run_full_test.sh` does

1. Verifies Kafka is reachable; aborts with a helpful message if not.
2. Starts the fire-detection stream processor (one or more, controlled by `--instances N`).
3. Starts the S3 upload consumer if `S3_BUCKET` is set.
4. Runs the producer against every video you passed on the command line.
5. Streams a per-video progress dashboard in the terminal until everything finishes.
6. Reports a summary of files written to `clips/` and (if configured) uploaded to S3.

Logs go to `logs/stream.log`, `logs/consumer.log`, `logs/producer.log`.

```bash
./scripts/run_full_test.sh --help
```

## Running components by hand

Sometimes you want each component in its own terminal so you can read the logs live.

### Terminal 1 — stream processor

```bash
python3 -m streams
```

Expected output:

```
✓ fire-detect-nn found in site-packages
Using fire-detect-nn from: /path/to/site-packages/fire_detect_nn
fire-detect-nn model initialized (DenseNet121)
Starting fire detection stream processor...
Consuming from topic: video-frames
Publishing to topic: fire-detections
```

### Terminal 2 — S3 upload consumer (optional)

```bash
python3 consumer/s3_video_consumer.py
```

Skip this if `S3_BUCKET` isn't set; the stream still writes annotated MP4s to `clips/` locally.

### Terminal 3 — producer

```bash
# Single video
python3 producer/video_producer.py path/to/your/video.mp4 some_video_id

# Or run a few videos in parallel through the same scripted helper
python3 scripts/test_with_videos.py video1.mp4 video2.mp4 video3.mp4
```

### Terminal 4 — watch results

```bash
# Status + offsets for all topics
python3 scripts/kafka_inspect.py status

# Formatted fire detections (default topic)
python3 scripts/kafka_inspect.py detections --limit 20

# Raw JSON dump of any topic
python3 scripts/kafka_inspect.py messages video-completions --limit 5
```

## Bringing your own video

Any standard format `cv2.VideoCapture` can open will work — `.mp4`, `.avi`, `.mov`, `.mkv`. Resolution is downscaled to `FRAME_WIDTH × FRAME_HEIGHT` (default 640×480) by the producer; tweak in `.env` if you want a different size.

There is no built-in test-video tree. The `test_files/` directory referenced in older docs has been removed — pass your own paths via CLI.

## Tests

```bash
# Full pytest suite
pytest

# Faster: skip slow integration tests
pytest -m "not slow"

# A specific module
pytest tests/test_fire_detection_stream.py -v
```

The suite covers:

- `test_video_producer.py` — frame encoding, Kafka send wiring
- `test_fire_detection_stream.py` — message handling, video writer state
- `test_model_loading.py` — model init for both fire-detect-nn and YOLOv8 paths
- `test_s3_upload_consumer.py` — completion-event handling, S3 upload flow
- `test_single_video_processing.py` — end-to-end with a single video
- `test_parallel_video_processing.py` — multiple videos through one stream
- `test_video_finalization_concurrency.py` — writer finalization race conditions
- `test_utils.py` — `convert_numpy_types` helper

CI runs the same `pytest` command; mirror it locally before you push.

## Local vs production differences

| Component | Local (Docker Compose) | AWS production |
|---|---|---|
| Kafka | Single broker, no replication | MSK Serverless, multi-AZ |
| Zookeeper | Docker container | Managed by MSK |
| Monitoring | Kafka UI on `:8081` | CloudWatch + MSK metrics |
| Scaling | Run more processes manually | ECS Fargate auto-scaling |
| Storage | `clips/` directory | S3 bucket |
| Cost | Free | Pay-as-you-go (see `infrastructure/docs/COST_OPTIMIZATION.md`) |

## Cleanup

```bash
docker-compose down            # Stop containers
docker-compose down -v         # Stop and delete all Kafka data
rm -rf clips/ logs/            # Remove local pipeline output
./scripts/stop_all.sh          # Kill any leftover Python processes
```

## Troubleshooting

### Stream processor isn't consuming anything

1. Confirm Kafka is up: `python3 scripts/kafka_inspect.py status`.
2. Are messages being produced? Check `video-frames` count is rising.
3. Is the consumer stuck on a bad offset from a previous run? `./scripts/reset_consumer_offsets.sh`.

### "No fire detected" on a fire video

1. Drop `CONFIDENCE_THRESHOLD` (try 0.3) and re-run.
2. Sanity-check the model loaded: the startup log prints which path it took.
3. Inspect raw probabilities: `python3 scripts/kafka_inspect.py detections --limit 50`.

### Annotated MP4 doesn't open

OpenCV picks a codec at runtime by probing what's available on your machine (`HEVC` → `hvc1` → `avc1` → `H264` → `mp4v`). If the file plays in `ffplay` but not your default player, the chosen codec may not be installed — try VLC, or transcode with `ffmpeg -i clips/your.mp4 -c:v libx264 out.mp4`.

### Kafka container won't start

```bash
lsof -i :9092 -i :2181   # Something else holding the port?
docker-compose down -v && docker-compose up -d
docker-compose logs kafka
```
