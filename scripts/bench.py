"""Micro-benchmark for FireWatch ML inference.

Runs the configured FireDetectionModel against every frame of a video and
reports per-frame latency (p50 / p95 / p99) and overall throughput. Bypasses
Kafka — purely measures the model + GradCAM + overlay path.

Usage:
    python3 scripts/bench.py path/to/video.mp4
    python3 scripts/bench.py path/to/video.mp4 --warmup 5 --batch-size 1

Use this before and after a performance change to get an apples-to-apples
comparison. Set ML_MODEL_TYPE / CONFIDENCE_THRESHOLD via env to switch
backends.
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: E402
from streams.models import FireDetectionModel  # noqa: E402
from streams.pipeline.overlay import overlay_heatmap_on_frame  # noqa: E402


def _percentile(values: list, pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def run(video_path: Path, warmup: int, max_frames: int | None, no_overlay: bool) -> None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        sys.exit(f"could not open {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print("=" * 70)
    print(f"FireWatch benchmark · {video_path.name}")
    print("=" * 70)
    print(f"Source       : {width}x{height} @ {source_fps:.1f} fps · {total_frames} frames")
    print(f"Backend      : ML_MODEL_TYPE={config.ML_MODEL_TYPE}")
    print(f"Threshold    : {config.CONFIDENCE_THRESHOLD}")
    print(f"Frame resize : {config.FRAME_WIDTH}x{config.FRAME_HEIGHT}")
    print(f"Heatmap blend: {'skipped' if no_overlay else f'alpha={config.CLIP_HEATMAP_OVERLAY_ALPHA}'}")
    print()

    model = FireDetectionModel()
    latencies_ms: list[float] = []
    fire_count = 0
    processed = 0

    print(f"Warming up for {warmup} frames...")
    overall_start = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.resize(frame, (config.FRAME_WIDTH, config.FRAME_HEIGHT))

        t0 = time.perf_counter()
        prediction = model.predict(frame)
        if not no_overlay:
            heatmap = prediction.get("heatmap")
            if heatmap is not None:
                _ = overlay_heatmap_on_frame(frame, heatmap)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        processed += 1
        if prediction.get("has_fire"):
            fire_count += 1

        # Skip warmup frames so first-call init costs (JIT, lazy load) don't
        # pollute the distribution.
        if processed > warmup:
            latencies_ms.append(elapsed_ms)

        if max_frames and processed >= max_frames:
            break

    wall_seconds = time.perf_counter() - overall_start
    cap.release()

    measured = len(latencies_ms)
    if measured == 0:
        sys.exit(f"only {processed} frame(s) processed — need more than --warmup ({warmup}) to report stats")

    print()
    print("=" * 70)
    print("Results")
    print("=" * 70)
    print(f"Processed    : {processed} frames ({warmup} warmup + {measured} measured)")
    print(f"Fire frames  : {fire_count}")
    print(f"Wall time    : {wall_seconds:.2f} s")
    print(f"Throughput   : {processed / wall_seconds:.1f} fps overall ({measured / sum(latencies_ms) * 1000:.1f} fps measured)")
    print()
    print(f"Latency p50  : {_percentile(latencies_ms, 50):.1f} ms")
    print(f"Latency p95  : {_percentile(latencies_ms, 95):.1f} ms")
    print(f"Latency p99  : {_percentile(latencies_ms, 99):.1f} ms")
    print(f"Latency mean : {statistics.fmean(latencies_ms):.1f} ms")
    print(f"Latency max  : {max(latencies_ms):.1f} ms")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path, help="Path to a video file.")
    parser.add_argument("--warmup", type=int, default=5, help="Frames to discard from stats (default: 5).")
    parser.add_argument("--max-frames", type=int, default=None, help="Cap processed frames.")
    parser.add_argument("--no-overlay", action="store_true", help="Skip heatmap blending — isolate the model+gradcam cost.")
    args = parser.parse_args(argv)
    if not args.video.exists():
        sys.exit(f"video not found: {args.video}")
    run(args.video, args.warmup, args.max_frames, args.no_overlay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
