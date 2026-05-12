"""Fetch real CC0 fire + forest footage from Pexels and build the verification fixtures.

Replaces the earlier synth (image-slideshow) approach. The clips here are
continuous video footage — the kind of input the deployed model will actually
see. Both source clips are Pexels CC0 (royalty-free, no attribution required).

Output (written next to this script; all gitignored via `*.mp4`):
  positive_fire.mp4    — continuous wildfire footage (downloaded as-is)
  negative_forest.mp4  — continuous forest-walk footage (downloaded, resized to 1080p)
  mixed_event.mp4      — first half of negative_forest + first half of positive_fire,
                         re-encoded to a single resolution/fps. This is two real
                         continuous segments concatenated, NOT a slideshow.
  ground_truth.json    — per-clip per-frame labels (all-1, all-0, half-then-half).

Sources (Pexels, CC0):
  positive_fire  → https://www.pexels.com/video/wild-fire-in-the-forest-4825780/
  negative_forest → https://www.pexels.com/video/a-man-walking-in-the-middle-of-the-forest-4158843/

Usage (from repo root):
    python tests/fixtures/trail_cam/fetch_real.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent

POSITIVE_URL = "https://videos.pexels.com/video-files/4825780/4825780-hd_1920_1080_30fps.mp4"
NEGATIVE_URL = "https://videos.pexels.com/video-files/4158843/4158843-uhd_2560_1440_24fps.mp4"

# Mixed-event params. The mixed clip is half negative + half positive at a
# unified resolution/fps so downstream tools see one consistent stream.
MIXED_FPS = 30
MIXED_SIZE = (1280, 720)  # (w, h) — keep aspect-ish but small enough for a quick verification pass
MIXED_HALF_FRAMES = 60


def _download(url: str, out_path: Path) -> None:
    if out_path.exists():
        print(f"  {out_path.name}: already present, skipping download")
        return
    print(f"  downloading {url} ...")
    urllib.request.urlretrieve(url, out_path)
    print(f"    → {out_path.name} ({out_path.stat().st_size / 1e6:.1f} MB)")


def _read_first_n(path: Path, n: int, size: tuple[int, int]) -> list:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        sys.exit(f"could not open {path}")
    frames = []
    while len(frames) < n:
        ok, frame = cap.read()
        if not ok:
            break
        if (frame.shape[1], frame.shape[0]) != size:
            frame = cv2.resize(frame, size)
        frames.append(frame)
    cap.release()
    if len(frames) < n:
        sys.exit(f"{path.name}: only {len(frames)} frames available, need {n}")
    return frames


def _build_mixed(neg_path: Path, pos_path: Path, out_path: Path) -> list[int]:
    neg_frames = _read_first_n(neg_path, MIXED_HALF_FRAMES, MIXED_SIZE)
    pos_frames = _read_first_n(pos_path, MIXED_HALF_FRAMES, MIXED_SIZE)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, MIXED_FPS, MIXED_SIZE)
    for f in neg_frames:
        writer.write(f)
    for f in pos_frames:
        writer.write(f)
    writer.release()

    labels = [0] * len(neg_frames) + [1] * len(pos_frames)
    print(f"  wrote {out_path.name} · {len(labels)} frames ({len(neg_frames)} neg + {len(pos_frames)} pos)")
    return labels


def _count_frames(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def main() -> int:
    pos_path = HERE / "positive_fire.mp4"
    neg_path = HERE / "negative_forest.mp4"
    mix_path = HERE / "mixed_event.mp4"

    print("Fetching real fixtures from Pexels (CC0)...")
    _download(POSITIVE_URL, pos_path)
    _download(NEGATIVE_URL, neg_path)
    print("Building mixed_event.mp4 from the two real clips...")
    mixed_labels = _build_mixed(neg_path, pos_path, mix_path)

    pos_frames = _count_frames(pos_path)
    neg_frames = _count_frames(neg_path)
    ground_truth = {
        "positive_fire": [1] * pos_frames,
        "negative_forest": [0] * neg_frames,
        "mixed_event": mixed_labels,
    }
    gt_path = HERE / "ground_truth.json"
    gt_path.write_text(json.dumps(ground_truth, indent=2))
    print(f"  wrote {gt_path.name}")

    print()
    print(f"positive_fire   : {pos_frames} frames, all labeled fire=1")
    print(f"negative_forest : {neg_frames} frames, all labeled fire=0")
    print(f"mixed_event     : {len(mixed_labels)} frames, first {MIXED_HALF_FRAMES} no-fire then {MIXED_HALF_FRAMES} fire")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
