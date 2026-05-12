"""Train/val transforms for the FireWatch classifier.

Both pipelines end with the same ``Normalize(RGB_MEAN, RGB_STD)`` step the
upstream fire-detect-nn package uses at inference. Imported from the upstream
package directly so we can't drift.
"""
from fire_detect_nn.datasets.combo import IMG_SHAPE, RGB_MEAN, RGB_STD
from torchvision import transforms


def build_val_transform():
    """Deterministic val/inference transform — matches upstream `combo.transform`."""
    return transforms.Compose(
        [
            transforms.Resize(IMG_SHAPE),
            transforms.ToTensor(),
            transforms.Normalize(mean=RGB_MEAN, std=RGB_STD),
        ]
    )


def build_train_transform():
    """Train-time augmentation. RandomResizedCrop scale matches typical fire imagery
    (the subject often occupies a large fraction of the frame, so don't crop too aggressively)."""
    return transforms.Compose(
        [
            transforms.RandomResizedCrop(IMG_SHAPE, scale=(0.7, 1.0)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
            transforms.ToTensor(),
            transforms.Normalize(mean=RGB_MEAN, std=RGB_STD),
        ]
    )
