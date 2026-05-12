"""Export a training checkpoint as a deployable FireWatch model.

Loads ``best.pt`` (sigmoid stripped during training), wraps it in a stock
``FireClassifier`` (which has ``nn.Sigmoid()`` at the head), writes the
state_dict to ``models/firewatch-v{N}.pt``, and emits a sidecar metadata
JSON. ``{N}`` auto-increments to the next free slot under ``models/``.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import torch

from streams.models.fire_classifier import FireClassifier


def next_version(models_dir: Path) -> int:
    """Find the next free v{N} under models/."""
    models_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r"firewatch-v(\d+)\.pt$")
    used = []
    for p in models_dir.iterdir():
        m = pattern.match(p.name)
        if m:
            used.append(int(m.group(1)))
    return (max(used) + 1) if used else 1


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Export a FireWatch checkpoint for deployment")
    parser.add_argument("--checkpoint", type=Path, required=True, help="Path to training-time .pt state_dict")
    parser.add_argument("--models_dir", type=Path, default=Path("models"))
    parser.add_argument("--version", type=int, default=None, help="Override auto-incremented version number")
    parser.add_argument("--threshold", type=float, default=0.5, help="Inference threshold recorded in metadata")
    args = parser.parse_args()

    if not args.checkpoint.exists():
        raise FileNotFoundError(f"checkpoint not found: {args.checkpoint}")

    # Load training state_dict into a stock FireClassifier (which already has Sigmoid).
    # Sigmoid has no params, so the state_dict from the logit-mode model loads cleanly.
    model = FireClassifier(backbone="densenet121", pretrained=False)
    state_dict = torch.load(args.checkpoint, map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval()

    version = args.version if args.version is not None else next_version(args.models_dir)
    out_path = args.models_dir / f"firewatch-v{version}.pt"
    meta_path = args.models_dir / f"firewatch-v{version}.metadata.json"

    torch.save(model.state_dict(), out_path)
    print(f"✓ Wrote {out_path}")

    # Best-effort: pull training metrics from the sibling best_metrics.json.
    metrics = {}
    best_metrics_path = args.checkpoint.parent / "best_metrics.json"
    if best_metrics_path.exists():
        try:
            metrics = json.loads(best_metrics_path.read_text())
        except Exception:
            metrics = {}

    train_config_path = args.checkpoint.parent / "config.json"
    train_config = {}
    if train_config_path.exists():
        try:
            train_config = json.loads(train_config_path.read_text())
        except Exception:
            train_config = {}

    metadata = {
        "version": version,
        "checkpoint_source": str(args.checkpoint),
        "exported_at": datetime.utcnow().isoformat(),
        "git_sha": git_sha(),
        "architecture": "FireClassifier(backbone=densenet121)",
        "input_shape": [3, 224, 224],
        "normalization": {"mean": [0.4005, 0.3702, 0.3419], "std": [0.2858, 0.2749, 0.2742]},
        "threshold": args.threshold,
        "dataset": "D-Fire (https://github.com/gaiasd/DFireDataset)",
        "training_metrics": metrics,
        "training_config": train_config,
    }
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Wrote {meta_path}")
    print(f"\nDeploy with:")
    print(f"  ML_MODEL_TYPE=firewatch FIREWATCH_MODEL_PATH={out_path} python -m streams")


if __name__ == "__main__":
    main()
