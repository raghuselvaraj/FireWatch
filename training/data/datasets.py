"""D-Fire dataset loader and downloader.

D-Fire (https://github.com/gaiasd/DFireDataset) ships YOLO-format annotations:
each ``.txt`` label file is either empty (no fire/smoke present) or contains
one line per bounding box. For binary fire/no-fire training we collapse:
non-empty label file → label 1, empty → label 0.

Expected on-disk layout after ``--download``::

    <cache_dir>/dfire/
    ├── train/
    │   ├── images/  *.jpg
    │   └── labels/  *.txt
    └── test/
        ├── images/
        └── labels/
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PIL import Image
from torch.utils.data import Dataset


DFIRE_REPO_URL = "https://github.com/gaiasd/DFireDataset.git"
DEFAULT_CACHE_ROOT = Path(os.path.expanduser(os.environ.get("FIREWATCH_CACHE_DIR", "~/.cache/firewatch")))
COMPLETE_MARKER = ".complete"


def default_dfire_root(cache_dir: Optional[Path] = None) -> Path:
    """Return ``<cache_dir>/dfire`` (resolving the cache root if not given)."""
    cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else DEFAULT_CACHE_ROOT
    return cache_dir / "dfire"


class DFireDataset(Dataset):
    """Binary fire/no-fire over D-Fire.

    Args:
        root: Directory containing ``train/`` and ``test/`` subdirectories.
        split: ``"train"`` or ``"test"``.
        transform: PIL → Tensor transform (e.g. from ``training.data.transforms``).
        indices: Optional list restricting which samples are exposed. Used by
            ``training.train`` to carve out a deterministic val slice from the
            train split without copying files around.
    """

    def __init__(
        self,
        root: Path,
        split: str = "train",
        transform: Optional[Callable] = None,
        indices: Optional[List[int]] = None,
    ):
        if split not in ("train", "test"):
            raise ValueError(f"split must be 'train' or 'test', got {split!r}")
        self.root = Path(root)
        self.split = split
        self.transform = transform

        images_dir = self.root / split / "images"
        labels_dir = self.root / split / "labels"
        if not images_dir.is_dir() or not labels_dir.is_dir():
            raise FileNotFoundError(
                f"Expected D-Fire layout at {self.root}: missing "
                f"{images_dir.relative_to(self.root)} or {labels_dir.relative_to(self.root)}.\n"
                "Run: python -m training.data.datasets --download"
            )

        # Build (image_path, label) pairs by pairing each image with its
        # same-stem label file. Images without a label file are treated as
        # no-fire (label 0) — D-Fire's convention is that missing labels
        # are negatives.
        samples: List[Tuple[Path, int]] = []
        for image_path in sorted(images_dir.iterdir()):
            if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            label_path = labels_dir / f"{image_path.stem}.txt"
            label = _label_from_yolo_file(label_path)
            samples.append((image_path, label))

        if not samples:
            raise RuntimeError(f"No images found in {images_dir}")

        self._samples = samples
        self._indices = list(range(len(samples))) if indices is None else list(indices)

    def __len__(self) -> int:
        return len(self._indices)

    def __getitem__(self, idx: int) -> Tuple:
        image_path, label = self._samples[self._indices[idx]]
        image = Image.open(image_path).convert("RGB")
        if self.transform is not None:
            image = self.transform(image)
        return image, label

    @property
    def labels(self) -> List[int]:
        """Labels in the order ``__getitem__`` returns them. Cheap; no I/O."""
        return [self._samples[i][1] for i in self._indices]


def _label_from_yolo_file(label_path: Path) -> int:
    """Binary collapse: any non-whitespace content → 1, else 0 (incl. missing)."""
    if not label_path.exists():
        return 0
    return 1 if label_path.read_text().strip() else 0


def download_dfire(cache_dir: Optional[Path] = None) -> Path:
    """Clone D-Fire to ``<cache_dir>/dfire`` if not already present.

    Idempotent — checks for a ``.complete`` marker to skip work on re-runs.
    Returns the dataset root path.
    """
    root = default_dfire_root(cache_dir)
    marker = root / COMPLETE_MARKER

    if marker.exists():
        print(f"✓ D-Fire already present at {root}")
        return root

    root.parent.mkdir(parents=True, exist_ok=True)

    if root.exists():
        # Partial clone from a previous failed run.
        print(f"Removing incomplete clone at {root}")
        shutil.rmtree(root)

    print(f"Cloning D-Fire from {DFIRE_REPO_URL} → {root}")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", DFIRE_REPO_URL, str(root)],
            check=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError("git is required to clone D-Fire") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"D-Fire clone failed (exit {e.returncode})") from e

    marker.touch()
    print(f"✓ D-Fire ready at {root}")
    return root


def print_class_balance(root: Path) -> None:
    """Sanity-check the dataset layout and print positive/negative counts per split."""
    for split in ("train", "test"):
        try:
            ds = DFireDataset(root=root, split=split, transform=None)
        except FileNotFoundError as e:
            print(f"⚠️  {split}: {e}")
            continue
        labels = ds.labels
        n = len(labels)
        pos = sum(labels)
        pct = (pos / n * 100) if n else 0.0
        print(f"{split:>5}: {n} images ({pos} positive, {pct:.1f}% fire)")


def _main():
    parser = argparse.ArgumentParser(description="D-Fire downloader / inspector")
    parser.add_argument("--download", action="store_true", help="Clone D-Fire to the cache dir")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Override cache root (default: $FIREWATCH_CACHE_DIR or ~/.cache/firewatch)",
    )
    args = parser.parse_args()

    root = default_dfire_root(args.cache_dir)
    if args.download:
        root = download_dfire(args.cache_dir)
    elif not root.exists():
        print(f"D-Fire not found at {root}. Re-run with --download.")
        sys.exit(1)

    print_class_balance(root)


if __name__ == "__main__":
    _main()
