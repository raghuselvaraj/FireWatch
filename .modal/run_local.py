"""Local mirror of `.modal/run_smoke.py` — for Local↔Modal comparison.

Same input → same output structure as `run_smoke.py`, but the FireWatch model
runs in-process instead of via a Modal remote call. Skips the Kafka pipeline
entirely (transport is independently tested by the unit suite); the only thing
this script exists for is to produce a JSON + annotated MP4 that's directly
diff-able against the Modal output.

Output:
  clips/local_<input-stem>_with_heatmaps.mp4
  clips/local_<input-stem>_predictions.json

Usage:
    python .modal/run_local.py tests/fixtures/trail_cam/positive_fire.mp4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from streams.models.firewatch import FireWatch  # noqa: E402
from streams.pipeline.overlay import overlay_heatmap_on_frame  # noqa: E402


def run(video_path: Path, max_frames: int | None, output_dir: Path) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        sys.exit(f"could not open {video_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"local_{video_path.stem}_with_heatmaps.mp4"
    json_path = output_dir / f"local_{video_path.stem}_predictions.json"

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, src_fps, (width, height))

    print(f"Source : {video_path.name} · {width}x{height}@{src_fps:.1f}fps · {total_frames} frames")
    print(f"Output : {out_path}")
    print()

    model = FireWatch(
        model_path=str(REPO_ROOT / "models" / "firewatch-v1.pt"),
        confidence_threshold=0.5,
        gradcam_every_n_fire_frames=1,
    )

    predictions: list[dict] = []
    fire_count = 0
    processed = 0
    t0 = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        result = model.predict(frame)

        heatmap = result.get("heatmap")
        annotated = overlay_heatmap_on_frame(frame, heatmap) if heatmap is not None else frame
        writer.write(annotated)

        predictions.append(
            {
                "frame": processed,
                "has_fire": bool(result.get("has_fire", False)),
                "fire_probability": float(result.get("fire_probability", 0.0)),
            }
        )
        if result.get("has_fire"):
            fire_count += 1

        processed += 1
        if processed % 25 == 0:
            elapsed = time.perf_counter() - t0
            print(f"  frame {processed}/{total_frames} · {processed / elapsed:.2f} fps · fire_frames={fire_count}")

        if max_frames is not None and processed >= max_frames:
            break

    cap.release()
    writer.release()

    elapsed = time.perf_counter() - t0
    json_path.write_text(json.dumps(predictions, indent=2))

    summary = {
        "video": str(video_path),
        "frames_processed": processed,
        "fire_frames": fire_count,
        "elapsed_s": elapsed,
        "fps": processed / elapsed if elapsed else 0.0,
        "fire_frame_rate": fire_count / processed if processed else 0.0,
        "output_video": str(out_path),
        "predictions_json": str(json_path),
    }
    print()
    print(f"Processed   : {processed} frames in {elapsed:.1f}s ({summary['fps']:.2f} fps)")
    print(f"Fire frames : {fire_count} ({summary['fire_frame_rate'] * 100:.1f}%)")
    print(f"Wrote       : {out_path}")
    print(f"Wrote       : {json_path}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path, help="Path to a video file.")
    parser.add_argument("--max-frames", type=int, default=None, help="Cap processed frames.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "clips",
        help="Output directory for annotated MP4 + predictions JSON.",
    )
    args = parser.parse_args(argv)
    if not args.video.exists():
        sys.exit(f"video not found: {args.video}")
    run(args.video, args.max_frames, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
