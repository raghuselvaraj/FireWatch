# Performance Optimization Guide

This guide explains how to optimize FireWatch stream processing for maximum throughput.

## Current Performance

**Default Configuration:**
- ~20-30 frames/second per stream processor
- Sequential frame processing
- GradCAM heatmap computation for every fire detection
- Synchronous Kafka operations

## Bottlenecks Identified

1. **Synchronous Kafka Operations**: Blocking on `future.get()` waits for acknowledgment
2. **GradCAM Computation**: Expensive gradient computation (core feature, but can be sampled for performance)
3. **Frame-by-Frame Processing**: No batching of ML inference
4. **Consumer Configuration**: Suboptimal fetch settings

## Optimizations Implemented

### 1. Async Kafka Operations ✅

**Before:**
```python
future = self.producer.send(...)
record_metadata = future.get(timeout=10)  # Blocks here!
```

**After:**
```python
future = self.producer.send(...)
# Use callbacks for async error handling (non-blocking)
future.add_callback(on_send_success)
future.add_errback(on_send_error)
```

**Impact**: Eliminates blocking on Kafka sends, allowing continuous processing.

### 2. Optimized Producer Configuration ✅

**Changes:**
- `acks=1` (instead of `'all'`) - Only wait for leader acknowledgment
- `compression_type='gzip'` - Compress messages for better throughput
- `batch_size=16384` - Batch messages for better throughput
- `linger_ms=10` - Wait up to 10ms to batch messages
- `max_in_flight_requests_per_connection=5` - Allow more in-flight requests

**Impact**: ~20-30% improvement in Kafka throughput.

### 3. Optimized Consumer Configuration ✅

**Changes:**
- `fetch_min_bytes=16384` (increased from 1024) - Wait for more data before returning
- `fetch_max_wait_ms=100` (reduced from 500) - Lower latency
- `max_partition_fetch_bytes=10485760` (10MB) - Increased buffer size

**Impact**: Better throughput with larger batches, lower latency.

### 4. GradCAM on Positive Frames Only ✅

GradCAM heatmaps are computed only for frames the classifier flags as fire (probability ≥ `CONFIDENCE_THRESHOLD`). Negative frames skip the expensive backward pass. If GradCAM fails (hook not registered, OOM, etc.) the frame is still written to the output video — just without the heatmap overlay.

Applies to fire-detect-nn only. YOLOv8 paths don't compute GradCAM.

## Performance Characteristics

**Default Configuration:**
- Processes all frames
- Computes GradCAM heatmap for every positive (fire) detection
- ~20-30 frames/second per processor

**With Optimizations (Async Kafka, Better Config):**
- ~30-40 frames/second per processor
- All frames processed
- Heatmap on every positive frame

## Phase 3 tuning knobs

Phase 3 introduced six environment-driven knobs. All have backward-compatible defaults and can be combined.

### Inference cadence

```env
INFERENCE_EVERY_N_FRAMES=2   # default 1 (every frame)
```

Run the model every Nth frame. Skipped frames still get written to the annotated MP4 — they reuse the most recent prediction's `has_fire` and heatmap. Set to 2 to roughly double FPS on high-FPS sources where consecutive frames are near-identical; set to 4 if you can tolerate ~0.13s of detection lag at 30 fps.

### GradCAM cadence

```env
GRADCAM_EVERY_N_FIRE_FRAMES=5   # default 5
```

GradCAM is the expensive part of fire-detect-nn's positive path (a full backward pass through DenseNet121). Most consecutive fire frames produce near-identical heatmaps, so this knob computes the heatmap only every Nth positive frame and reuses it on the frames in between. Set to 1 to compute on every positive frame (legacy behavior).

### Mixed precision (CUDA only)

The fire-detect-nn backend automatically wraps inference in `torch.autocast(device_type="cuda", dtype=torch.float16)` when running on CUDA. On Apple MPS it stays fp32 (autocast on MPS is still flaky in torch 2.x). No env knob — automatic.

### Frame transport

```env
FRAME_TRANSPORT=msgpack       # default; legacy: base64-json
```

`msgpack` packs raw JPEG bytes directly into the Kafka message (no base64 wrap). ~33% smaller payload on the wire, ~5x faster decode in the stream processor. The producer and stream **must** agree on this setting — they read the same env var.

### Offset commit cadence

```env
COMMIT_EVERY_N_MESSAGES=250    # default 250
COMMIT_INTERVAL_SECONDS=5.0    # default 5.0
```

The stream commits Kafka offsets whenever **either** threshold fires. The time-interval guard fixes the historical "short videos never see a commit" bug — without it, a 911-frame video left 161 messages uncommitted at the end, and `run_full_test.sh`'s lag check would poll forever.

### Eval-safe GradCAM (no env knob)

Phase 3 dropped the legacy `model.train(); backward(); model.eval()` toggle that GradCAM used to enable gradient computation. That toggle silently changed BatchNorm to batch-stats mode mid-inference, distorting the very activations GradCAM was trying to weigh. The new path uses `torch.enable_grad()` on the input tensor only, keeping the model in eval mode end-to-end. Also swapped the deprecated `register_backward_hook` for `register_full_backward_hook`.

## Measuring

```bash
python3 scripts/bench.py path/to/video.mp4 --warmup 5
```

Reports throughput and p50/p95/p99 latency. Bypasses Kafka entirely — purely measures the model + GradCAM + overlay path. Set env knobs before invoking to compare configurations. Example:

```bash
# Baseline
python3 scripts/bench.py sample.mp4

# Run inference every other frame
INFERENCE_EVERY_N_FRAMES=2 python3 scripts/bench.py sample.mp4

# Disable GradCAM cadence (compute on every positive)
GRADCAM_EVERY_N_FIRE_FRAMES=1 python3 scripts/bench.py sample.mp4
```

> Note: bench.py calls the model directly, so `INFERENCE_EVERY_N_FRAMES` won't change the numbers here — that knob lives in the stream wrapper. To measure its effect, run an end-to-end pipeline (`run_full_test.sh`) and compare wall-clock to completion.

> **Still deferred:** batched inference (collect N frames into a single forward pass). This is the biggest remaining theoretical win on CUDA, but it requires restructuring the consumer loop and would block this PR.

## Horizontal Scaling

To process more videos faster, run multiple stream processors:

```bash
# Terminal 1
python3 -m streams

# Terminal 2
python3 -m streams

# Terminal 3
python3 -m streams

# ... up to N instances (where N = number of partitions)
```

**With 6 partitions and optimized settings:**
- Maximum Speed: ~360-480 frames/second total
- Balanced: ~180-240 frames/second total
- Maximum Accuracy: ~120-180 frames/second total

## Monitoring Performance

### Check Processing Rate

The stream processor prints progress every 10 frames:
```
Processed 100 frames (skipped 0)... (latest: frame 100 from video video1)
```

### Check Kafka Lag

```bash
# Check consumer lag
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group fire-detection-stream --describe
```

### Check Throughput

Monitor frames/second:
- Count messages processed over time
- Divide by elapsed time
- Target: 20-80 fps per processor (depending on configuration)

## Additional Optimizations

### 1. Use GPU for ML Inference

If you have a GPU available:
- PyTorch will automatically use CUDA if available
- Check with: `python3 -c "import torch; print(torch.cuda.is_available())"`
- **Impact**: ~5-10x faster ML inference

### 2. Increase Partitions

For more parallel processing:
```bash
# Recreate topics with more partitions
kafka-topics.sh --bootstrap-server localhost:9092 \
  --alter --topic video-frames --partitions 12
```

**Impact**: Allows up to 12 parallel processors

### 3. Use Smaller Frame Sizes

Reduce frame dimensions for faster processing and smaller video files:
```env
FRAME_WIDTH=320
FRAME_HEIGHT=240
```

**Impact**: 
- ~2-3x faster ML inference (with reduced accuracy)
- ~4x smaller video file size (640x480 → 320x240 = 4x fewer pixels)

### 4. Adjust Frame Extraction Interval

Extract fewer frames from source videos:
```env
FRAME_EXTRACTION_INTERVAL=2  # Extract every 2nd frame
```

**Impact**: ~50% fewer frames to process

**Note**: This affects the producer (video extraction), not the stream processor

## Performance Comparison

| Configuration | FPS/Processor | Total (6 partitions) | Heatmaps |
|--------------|---------------|---------------------|----------|
| **Default** | 20-30 | 120-180 | All (every fire) |
| **Optimized** | 30-40 | 180-240 | All (every fire) |

## Troubleshooting

### Still Too Slow?

1. **Check CPU usage**: ML inference is CPU-bound
   - Solution: Use GPU or reduce frame size

2. **Check Kafka lag**: If lag is high, add more processors
   - Solution: Run more stream processor instances

3. **Check frame extraction**: Producer might be slow
   - Solution: Increase `FRAME_EXTRACTION_INTERVAL` in producer config

4. **Check video writing**: Disk I/O might be bottleneck
   - Solution: Use faster storage (SSD)

### Not Processing Fast Enough?

1. **Increase partitions**: More parallel processing
2. **Run more processors**: Scale horizontally
3. **Use GPU**: 5-10x faster ML inference
4. **Reduce frame size**: Smaller frames = faster inference

## Best Practices

1. **Start with balanced configuration** - Good speed/accuracy trade-off
2. **Monitor consumer lag** - Ensure processors keep up
3. **Scale horizontally** - Add more processors before optimizing single processor
4. **Use GPU if available** - Biggest single performance improvement
5. **Tune based on use case** - Speed vs accuracy trade-off

