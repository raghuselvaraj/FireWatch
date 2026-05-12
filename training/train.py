"""Train the FireWatch DenseNet121 classifier on D-Fire.

Quickstart:
    python -m training.train --config training/configs/default.yaml
    python -m training.train --epochs 2 --batch_size 16            # smoke test
    python -m training.train --max_steps 4                          # 4 batches per epoch

Best-AUROC checkpoint lands at ``training/runs/<run_id>/best.pt``; ``last.pt``
is also written each epoch for resuming. ``training/export.py`` turns
``best.pt`` into a deployable ``models/firewatch-v{N}.pt`` with the sigmoid
re-attached.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import yaml
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR, LinearLR, SequentialLR
from torch.utils.data import DataLoader

from training.data.datasets import DFireDataset, default_dfire_root, download_dfire
from training.data.transforms import build_train_transform, build_val_transform
from training.model import build_model


def select_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_config(config_path: Optional[Path]) -> Dict[str, Any]:
    if config_path is None:
        return {}
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def _get(cfg: Dict[str, Any], path: str, default: Any) -> Any:
    """Nested-dict lookup with dotted path: ``_get(cfg, 'training.lr', 1e-4)``."""
    node: Any = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def make_split_indices(n_train: int, val_frac: float, seed: int) -> Tuple[List[int], List[int]]:
    """Deterministic shuffle, then carve `val_frac` off the front for val."""
    rng = np.random.default_rng(seed)
    indices = np.arange(n_train)
    rng.shuffle(indices)
    n_val = int(np.floor(val_frac * n_train))
    return indices[n_val:].tolist(), indices[:n_val].tolist()


def make_dataloaders(
    dfire_root: Path,
    val_frac: float,
    val_seed: int,
    batch_size: int,
    num_workers: int,
) -> Tuple[DataLoader, DataLoader]:
    # First pass to discover total train sample count (no transform; cheap).
    full_train = DFireDataset(dfire_root, split="train", transform=None)
    train_idxs, val_idxs = make_split_indices(len(full_train), val_frac, val_seed)

    train_ds = DFireDataset(
        dfire_root, split="train", transform=build_train_transform(), indices=train_idxs
    )
    val_ds = DFireDataset(
        dfire_root, split="train", transform=build_val_transform(), indices=val_idxs
    )

    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=False,
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=False,
    )
    return train_loader, val_loader


def make_scheduler(optimizer: AdamW, warmup_epochs: int, total_epochs: int):
    """LinearLR warmup → CosineAnnealingLR. Stepped per epoch."""
    if warmup_epochs <= 0:
        return CosineAnnealingLR(optimizer, T_max=total_epochs)
    warmup = LinearLR(optimizer, start_factor=0.1, end_factor=1.0, total_iters=warmup_epochs)
    cosine = CosineAnnealingLR(optimizer, T_max=max(1, total_epochs - warmup_epochs))
    return SequentialLR(optimizer, schedulers=[warmup, cosine], milestones=[warmup_epochs])


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: AdamW,
    device: torch.device,
    writer,
    global_step: int,
    log_every_n_steps: int,
    max_steps: Optional[int],
) -> Tuple[float, int]:
    from tqdm import tqdm

    model.train()
    losses: List[float] = []
    skipped = 0
    pbar = tqdm(loader, desc="train", leave=False)
    for step, (images, labels) in enumerate(pbar):
        if max_steps is not None and step >= max_steps:
            break
        # non_blocking=True triggered numerical corruption on MPS during smoke
        # testing — sync transfers are barely slower and keep autograd sane.
        images = images.to(device)
        labels = labels.float().to(device).unsqueeze(1)

        optimizer.zero_grad()
        logits = model(images)
        loss = criterion(logits, labels)
        # Skip batches that produce non-finite loss (rare MPS-side instability
        # at the very start of training); also catches any future regression.
        if not torch.isfinite(loss):
            skipped += 1
            optimizer.zero_grad()
            continue
        loss.backward()
        # Standard precaution for fine-tuning a pretrained backbone with a
        # randomly-initialized head — bounds early gradients while the new
        # Linear settles into a sensible scale.
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()

        loss_val = loss.item()
        losses.append(loss_val)
        global_step += 1
        if global_step % log_every_n_steps == 0:
            writer.add_scalar("train/loss", loss_val, global_step)
            pbar.set_postfix(loss=f"{loss_val:.4f}")
    if skipped:
        print(f"  (skipped {skipped} non-finite-loss batches this epoch)")

    return float(np.mean(losses)) if losses else 0.0, global_step


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    max_steps: Optional[int] = None,
) -> Dict[str, float]:
    from tqdm import tqdm

    model.eval()
    all_probs: List[float] = []
    all_labels: List[int] = []
    losses: List[float] = []
    sigmoid = nn.Sigmoid()
    for step, (images, labels) in enumerate(tqdm(loader, desc="val", leave=False)):
        if max_steps is not None and step >= max_steps:
            break
        images = images.to(device)
        labels_t = labels.float().to(device).unsqueeze(1)
        logits = model(images)
        loss = criterion(logits, labels_t)
        losses.append(loss.item())
        probs = sigmoid(logits).cpu().numpy().ravel()
        all_probs.extend(probs.tolist())
        all_labels.extend(labels.cpu().numpy().tolist())

    from sklearn.metrics import average_precision_score, roc_auc_score

    metrics = {"val_loss": float(np.mean(losses)) if losses else 0.0}
    # AUROC/PR-AUC require both classes present in the labels.
    if len(set(all_labels)) >= 2:
        metrics["val_auroc"] = float(roc_auc_score(all_labels, all_probs))
        metrics["val_pr_auc"] = float(average_precision_score(all_labels, all_probs))
    else:
        metrics["val_auroc"] = 0.0
        metrics["val_pr_auc"] = 0.0
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Train FireWatch DenseNet121 on D-Fire")
    parser.add_argument("--config", type=Path, default=Path("training/configs/default.yaml"))
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--batch_size", type=int, default=None)
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--num_workers", type=int, default=None)
    parser.add_argument("--max_steps", type=int, default=None, help="Cap batches per epoch (smoke test)")
    parser.add_argument("--cache_dir", type=Path, default=None, help="Override D-Fire cache root")
    parser.add_argument("--run_id", type=str, default=None, help="Override the run id (default: timestamp)")
    parser.add_argument("--no-download", action="store_true", help="Don't attempt to download D-Fire if missing")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Resolve all hyperparameters: CLI overrides YAML, YAML overrides built-in defaults.
    epochs = args.epochs if args.epochs is not None else _get(cfg, "training.epochs", 20)
    batch_size = args.batch_size if args.batch_size is not None else _get(cfg, "training.batch_size", 32)
    lr = args.lr if args.lr is not None else float(_get(cfg, "training.lr", 1e-4))
    weight_decay = float(_get(cfg, "training.weight_decay", 1e-4))
    warmup_epochs = int(_get(cfg, "training.warmup_epochs", 1))
    num_workers = args.num_workers if args.num_workers is not None else _get(cfg, "data.num_workers", 4)
    val_frac = float(_get(cfg, "data.val_frac", 0.1))
    val_seed = int(_get(cfg, "data.val_seed", 4822))
    pretrained = bool(_get(cfg, "model.pretrained", True))
    backbone = _get(cfg, "model.backbone", "densenet121")
    run_dir_root = Path(_get(cfg, "logging.run_dir", "training/runs"))
    log_every_n_steps = int(_get(cfg, "logging.log_every_n_steps", 50))

    # Reproducibility — fix Python/numpy/torch seeds.
    random.seed(val_seed)
    np.random.seed(val_seed)
    torch.manual_seed(val_seed)

    device = select_device()
    print(f"Device: {device}")

    # Dataset
    dfire_root = default_dfire_root(args.cache_dir)
    if not dfire_root.exists() and not args.no_download:
        download_dfire(args.cache_dir)
    train_loader, val_loader = make_dataloaders(
        dfire_root, val_frac=val_frac, val_seed=val_seed, batch_size=batch_size, num_workers=num_workers
    )
    print(f"Train batches: {len(train_loader)}, Val batches: {len(val_loader)}")

    # Model / loss / optim
    model = build_model(pretrained=pretrained, backbone=backbone).to(device)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = make_scheduler(optimizer, warmup_epochs=warmup_epochs, total_epochs=epochs)

    # Run dir
    from torch.utils.tensorboard import SummaryWriter

    run_id = args.run_id or datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    run_dir = run_dir_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    writer = SummaryWriter(log_dir=str(run_dir))
    print(f"Run dir: {run_dir}")

    # Save the resolved config for traceability.
    with open(run_dir / "config.json", "w") as f:
        json.dump(
            {
                "epochs": epochs, "batch_size": batch_size, "lr": lr, "weight_decay": weight_decay,
                "warmup_epochs": warmup_epochs, "num_workers": num_workers, "val_frac": val_frac,
                "val_seed": val_seed, "pretrained": pretrained, "backbone": backbone,
                "device": str(device), "max_steps": args.max_steps,
                "started_at": datetime.utcnow().isoformat(),
            },
            f,
            indent=2,
        )

    best_auroc = -1.0
    global_step = 0
    for epoch in range(1, epochs + 1):
        t0 = time.time()
        train_loss, global_step = train_one_epoch(
            model, train_loader, criterion, optimizer, device,
            writer, global_step, log_every_n_steps, args.max_steps,
        )
        val_metrics = evaluate(model, val_loader, criterion, device, max_steps=args.max_steps)
        scheduler.step()
        elapsed = time.time() - t0

        writer.add_scalar("train/loss_epoch", train_loss, epoch)
        writer.add_scalar("val/loss", val_metrics["val_loss"], epoch)
        writer.add_scalar("val/auroc", val_metrics["val_auroc"], epoch)
        writer.add_scalar("val/pr_auc", val_metrics["val_pr_auc"], epoch)
        writer.add_scalar("lr", optimizer.param_groups[0]["lr"], epoch)

        print(
            f"epoch {epoch:>3}/{epochs}  "
            f"train_loss={train_loss:.4f}  "
            f"val_loss={val_metrics['val_loss']:.4f}  "
            f"auroc={val_metrics['val_auroc']:.4f}  "
            f"pr_auc={val_metrics['val_pr_auc']:.4f}  "
            f"({elapsed:.1f}s)"
        )

        torch.save(model.state_dict(), run_dir / "last.pt")
        if val_metrics["val_auroc"] > best_auroc:
            best_auroc = val_metrics["val_auroc"]
            torch.save(model.state_dict(), run_dir / "best.pt")
            with open(run_dir / "best_metrics.json", "w") as f:
                json.dump({"epoch": epoch, **val_metrics}, f, indent=2)

    writer.close()
    print(f"\n✓ Training complete. Best val AUROC: {best_auroc:.4f}")
    print(f"Checkpoint: {run_dir}/best.pt")
    print(f"Next: python -m training.export --checkpoint {run_dir}/best.pt")


if __name__ == "__main__":
    main()
