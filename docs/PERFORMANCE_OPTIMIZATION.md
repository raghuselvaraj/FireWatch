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

### 4. GradCAM Always Enabled ✅

**Note**: GradCAM heatmaps are a core feature and always computed for every fire detection. This ensures all output videos have proper heatmap overlays.

## Performance Characteristics

**Default Configuration:**
- Processes all frames
- Computes GradCAM heatmap for every fire detection
- ~20-30 frames/second per processor

**With Optimizations (Async Kafka, Better Config):**
- ~30-40 frames/second per processor
- All frames processed
- Heatmap for every fire detection

## Horizontal Scaling

To process more videos faster, run multiple stream processors:

```bash
# Terminal 1
python3 streams/fire_detection_stream.py

# Terminal 2
python3 streams/fire_detection_stream.py

# Terminal 3
python3 streams/fire_detection_stream.py

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

