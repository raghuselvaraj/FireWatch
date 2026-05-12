"""Build synthetic verification MP4s from the D-Fire test set.

Real trail-cam clips are the gold-standard input for this verification step
(see this directory's README). When they aren't available, this script
generates the next best thing: image-sequence MP4s built from D-Fire test
images. Because each D-Fire image has a known fire/no-fire label, the
resulting videos have **per-frame ground truth** — better than raw trail-cam
footage for accuracy measurement, worse than trail-cam footage for testing
real-world video characteristics (motion blur, lighting drift, codec).

Output (written to this directory; gitignored):
  positive_fire.mp4    — 120 fire-positive frames @ 10 fps
  negative_forest.mp4  — 120 fire-negative frames @ 10 fps
  mixed_event.mp4      — 60 negative + 60 positive frames @ 10 fps (ignition)
  ground_truth.json    — per-clip per-frame label, for results.md scoring

Usage:
    python tests/fixtures/trail_cam/build_synth.py
    python tests/fixtures/trail_cam/build_synth.py --frames 60 --fps 8

Requires the D-Fire cache at `~/.cache/firewatch/dfire/test/`. If missing,
prints the bootstrap path from `training/data/datasets.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import cv2

DFIRE_TEST = Path(os.path.expanduser(os.environ.get("FIREWATCH_CACHE_DIR", "~/.cache/firewatch"))) / "dfire" / "test"
HERE = Path(__file__).resolve().parent


def _partition(seed: int) -> tuple[list[Path], list[Path]]:
    images_dir = DFIRE_TEST / "images"
    labels_dir = DFIRE_TEST / "labels"
    if not images_dir.is_dir() or not labels_dir.is_dir():
        sys.exit(
            f"D-Fire test set not found at {DFIRE_TEST}. "
            "Materialize it via the bootstrap path in training/data/datasets.py."
        )

    positives: list[Path] = []
    negatives: list[Path] = []
    for img_path in sorted(images_dir.iterdir()):
        if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        label_path = labels_dir / f"{img_path.stem}.txt"
        if label_path.exists() and label_path.read_text().strip():
            positives.append(img_path)
        else:
            negatives.append(img_path)

    rng = random.Random(seed)
    rng.shuffle(positives)
    rng.shuffle(negatives)
    return positives, negatives


def _write_video(
    name: str,
    frames_with_labels: list[tuple[Path, int]],
    fps: int,
    output_dir: Path,
) -> tuple[Path, list[int]]:
    if not frames_with_labels:
        sys.exit(f"{name}: empty frame list")

    sample = cv2.imread(str(frames_with_labels[0][0]))
    if sample is None:
        sys.exit(f"could not read {frames_with_labels[0][0]}")
    h, w = sample.shape[:2]

    out_path = output_dir / f"{name}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))

    truth: list[int] = []
    for img_path, label in frames_with_labels:
        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"  warn: could not read {img_path.name}, skipping", file=sys.stderr)
            continue
        if frame.shape[:2] != (h, w):
            frame = cv2.resize(frame, (w, h))
        writer.write(frame)
        truth.append(label)
    writer.release()

    print(f"  wrote {out_path.name} · {len(truth)} frames · {sum(truth)} positive")
    return out_path, truth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", type=int, default=120, help="Frames per clip (default 120).")
    parser.add_argument("--fps", type=int, default=10, help="Output FPS (default 10).")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for image selection.")
    args = parser.parse_args(argv)

    print(f"Building synth fixtures from {DFIRE_TEST}...")
    positives, negatives = _partition(args.seed)
    print(f"  available: {len(positives)} fire / {len(negatives)} no-fire")

    if len(positives) < args.frames or len(negatives) < args.frames:
        sys.exit("not enough images in D-Fire test set for the requested frame count")

    pos_only = [(p, 1) for p in positives[: args.frames]]
    neg_only = [(p, 0) for p in negatives[: args.frames]]
    half = args.frames // 2
    mixed = [(p, 0) for p in negatives[args.frames : args.frames + half]] + [
        (p, 1) for p in positives[args.frames : args.frames + half]
    ]

    ground_truth: dict[str, list[int]] = {}
    _, ground_truth["positive_fire"] = _write_video("positive_fire", pos_only, args.fps, HERE)
    _, ground_truth["negative_forest"] = _write_video("negative_forest", neg_only, args.fps, HERE)
    _, ground_truth["mixed_event"] = _write_video("mixed_event", mixed, args.fps, HERE)

    gt_path = HERE / "ground_truth.json"
    gt_path.write_text(json.dumps(ground_truth, indent=2))
    print(f"  wrote {gt_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
