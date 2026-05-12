"""Evaluate a FireWatch checkpoint on the D-Fire test split.

Reports AUROC, PR-AUC, and a precision/recall/F1 table across a sweep of
thresholds. Operates on a logit-mode checkpoint (the kind ``train.py`` writes
to ``best.pt`` / ``last.pt``).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from training.data.datasets import DFireDataset, default_dfire_root
from training.data.transforms import build_val_transform
from training.model import build_model
from training.train import select_device


@torch.no_grad()
def collect_predictions(model: nn.Module, loader: DataLoader, device: torch.device):
    from tqdm import tqdm

    model.eval()
    sigmoid = nn.Sigmoid()
    probs, labels = [], []
    for images, lbls in tqdm(loader, desc="eval"):
        images = images.to(device)
        logits = model(images)
        probs.extend(sigmoid(logits).cpu().numpy().ravel().tolist())
        labels.extend(lbls.cpu().numpy().tolist())
    return np.array(labels), np.array(probs)


def threshold_sweep(labels: np.ndarray, probs: np.ndarray, thresholds=None):
    from sklearn.metrics import confusion_matrix

    thresholds = thresholds or [0.3, 0.4, 0.5, 0.6, 0.7]
    rows = []
    for thr in thresholds:
        preds = (probs >= thr).astype(int)
        tn, fp, fn, tp = confusion_matrix(labels, preds, labels=[0, 1]).ravel()
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        rows.append({"threshold": thr, "precision": precision, "recall": recall,
                     "f1": f1, "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)})
    return rows


def main():
    parser = argparse.ArgumentParser(description="Evaluate a FireWatch checkpoint")
    parser.add_argument("--checkpoint", type=Path, required=True, help="Path to .pt state_dict")
    parser.add_argument("--cache_dir", type=Path, default=None)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--num_workers", type=int, default=4)
    parser.add_argument("--split", type=str, default="test", choices=["train", "test"])
    args = parser.parse_args()

    device = select_device()
    print(f"Device: {device}")

    model = build_model(pretrained=False)
    state_dict = torch.load(args.checkpoint, map_location=device)
    model.load_state_dict(state_dict)
    model.to(device)

    dfire_root = default_dfire_root(args.cache_dir)
    ds = DFireDataset(dfire_root, split=args.split, transform=build_val_transform())
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)
    print(f"{args.split}: {len(ds)} images")

    from sklearn.metrics import average_precision_score, roc_auc_score

    labels, probs = collect_predictions(model, loader, device)

    auroc = roc_auc_score(labels, probs) if len(set(labels.tolist())) >= 2 else 0.0
    pr_auc = average_precision_score(labels, probs) if len(set(labels.tolist())) >= 2 else 0.0
    sweep = threshold_sweep(labels, probs)

    print(f"\nSplit: {args.split}")
    print(f"AUROC : {auroc:.4f}")
    print(f"PR-AUC: {pr_auc:.4f}")
    print(f"\n{'thr':>5}  {'prec':>6}  {'rec':>6}  {'f1':>6}  {'tp':>5}  {'fp':>5}  {'fn':>5}  {'tn':>5}")
    for r in sweep:
        print(f"{r['threshold']:>5.2f}  {r['precision']:>6.3f}  {r['recall']:>6.3f}  "
              f"{r['f1']:>6.3f}  {r['tp']:>5}  {r['fp']:>5}  {r['fn']:>5}  {r['tn']:>5}")

    report = {"split": args.split, "auroc": float(auroc), "pr_auc": float(pr_auc),
              "threshold_sweep": sweep, "n_samples": len(labels)}
    report_path = args.checkpoint.parent / f"eval_{args.split}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()
