"""DFireDataset reads the YOLO-format directory shape and collapses to binary."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from training.data.datasets import DFireDataset


def _make_jpg(path: Path, color=(255, 100, 100)):
    """Create a minimal solid-color JPEG so PIL doesn't choke on empties."""
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((32, 32, 3), dtype=np.uint8)
    arr[:] = color
    Image.fromarray(arr).save(path)


def _make_fixture(root: Path):
    """Build a 4-image D-Fire fixture: 2 positive (non-empty .txt), 2 negative (empty)."""
    images_dir = root / "train" / "images"
    labels_dir = root / "train" / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    _make_jpg(images_dir / "pos_001.jpg")
    _make_jpg(images_dir / "pos_002.jpg")
    _make_jpg(images_dir / "neg_001.jpg")
    _make_jpg(images_dir / "neg_002.jpg")

    # YOLO format: <class> <cx> <cy> <w> <h> (all normalized).
    (labels_dir / "pos_001.txt").write_text("0 0.5 0.5 0.3 0.3\n")
    (labels_dir / "pos_002.txt").write_text("1 0.4 0.4 0.2 0.2\n")
    (labels_dir / "neg_001.txt").write_text("")
    (labels_dir / "neg_002.txt").write_text("   \n")  # whitespace-only is still negative

    # Also need test/ to exist for the constructor's structure check on `test`
    # if anyone instantiates it — but the test only constructs `train`.
    return root


def test_dfire_dataset_binary_collapse(tmp_path):
    root = _make_fixture(tmp_path)
    ds = DFireDataset(root=root, split="train", transform=None)

    assert len(ds) == 4
    # Order is deterministic: sorted filename order from `iterdir`.
    # neg_001, neg_002, pos_001, pos_002 → labels [0, 0, 1, 1].
    assert ds.labels == [0, 0, 1, 1]


def test_dfire_dataset_applies_transform(tmp_path):
    from training.data.transforms import build_val_transform

    root = _make_fixture(tmp_path)
    ds = DFireDataset(root=root, split="train", transform=build_val_transform())

    image, label = ds[0]
    # build_val_transform Resize→ToTensor→Normalize → CHW float tensor
    assert image.ndim == 3
    assert image.shape[0] == 3
    assert image.shape[1] == 224 and image.shape[2] == 224
    assert label in (0, 1)


def test_dfire_dataset_indices_subset(tmp_path):
    root = _make_fixture(tmp_path)
    # Take only the positive half (sorted order: neg, neg, pos, pos → indices 2, 3).
    ds = DFireDataset(root=root, split="train", transform=None, indices=[2, 3])
    assert len(ds) == 2
    assert ds.labels == [1, 1]


def test_dfire_dataset_missing_layout_errors(tmp_path):
    # No train/images, no train/labels — should raise.
    with pytest.raises(FileNotFoundError):
        DFireDataset(root=tmp_path, split="train", transform=None)
