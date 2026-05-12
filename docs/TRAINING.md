# Training the FireWatch model

The `training/` package trains a DenseNet121 binary fire/no-fire classifier on
the public [D-Fire](https://github.com/gaiasd/DFireDataset) dataset using the
same `FireClassifier` architecture the stream's classifier backend uses. The
resulting checkpoint is drop-in: load it via `ML_MODEL_TYPE=firewatch` and the
existing inference path takes over.

## Prerequisites

- Python 3.11+, dependencies from `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  ```
  No external ML packages beyond `requirements.txt` are needed — the
  `FireClassifier` architecture and input normalization are defined locally
  in [`streams/models/fire_classifier.py`](../streams/models/fire_classifier.py)
  and [`streams/models/preprocessing.py`](../streams/models/preprocessing.py).
- ~5 GB free disk for D-Fire (cloned into `~/.cache/firewatch/dfire/` by default).
- Apple Silicon (MPS) or NVIDIA GPU recommended. CPU works but is slow.

## Quickstart

```bash
# 1. Fetch the dataset (one-time, ~5 GB)
python3 -m training.data.datasets --download
# prints class balance: e.g. "train: 17211 images (10246 positive, 59.5% fire)"

# 2. Smoke test — verifies the pipeline runs end-to-end without crashing
python3 -m training.train --epochs 2 --batch_size 16 --max_steps 4

# 3. Full training (~1.5–2.5 hours on Apple M-series)
python3 -m training.train --config training/configs/default.yaml

# 4. Evaluate on the held-out test split
python3 -m training.eval --checkpoint training/runs/<run_id>/best.pt

# 5. Export the deployable checkpoint to models/firewatch-v1.pt
python3 -m training.export --checkpoint training/runs/<run_id>/best.pt
```

The exported checkpoint is then loadable by the stream:

```bash
ML_MODEL_TYPE=firewatch FIREWATCH_MODEL_PATH=models/firewatch-v1.pt python3 -m streams
```

## Default hyperparameters

Defined in [`training/configs/default.yaml`](../training/configs/default.yaml).

| Param | Value | Notes |
|---|---|---|
| `model.backbone` | `densenet121` | Matches upstream fire-detect-nn; required for the inference path to work unchanged. |
| `model.pretrained` | `true` | ImageNet init. |
| `training.batch_size` | 32 | Fits MPS comfortably at 224×224. |
| `training.epochs` | 20 | ~12k optimizer steps on D-Fire train. |
| `training.lr` | 1e-4 | AdamW. |
| `training.weight_decay` | 1e-4 | |
| `training.warmup_epochs` | 1 | LinearLR → CosineAnnealingLR. |
| `data.val_frac` | 0.1 | 10% of `train/` held out as val (seed 4822 — matches upstream). |
| `data.num_workers` | 4 | Drop to 0 if MPS multiprocessing flakes. |

Override any of these via CLI flags or by editing the YAML.

## How the architecture stays in sync with inference

The deployed `streams/models/firewatch.py` backend instantiates the upstream
`FireClassifier(backbone="densenet121", pretrained=False)` and loads our
state_dict on top. To make a training-time model produce the same
`state_dict` keys:

- `training/model.py:build_model` instantiates `FireClassifier(pretrained=True)`,
  then **replaces `model.sigmoid` with `nn.Identity()`**. This lets training
  use `BCEWithLogitsLoss` against logits (numerically stable).
- `training/export.py` loads `best.pt` into a stock `FireClassifier`
  (which has `nn.Sigmoid()` at the head) and re-saves. The sigmoid module
  has no parameters, so the state_dict is identical either way.

End result: `models/firewatch-v{N}.pt` is structurally identical to the
legacy fire-detect-nn checkpoint format and uses the same input normalization
(`mean=(0.4005, 0.3702, 0.3419)`, `std=(0.2858, 0.2749, 0.2742)`, 224×224)
defined in [`streams/models/preprocessing.py`](../streams/models/preprocessing.py).

## Dataset details

D-Fire ships with `train/` and `test/` subdirectories of YOLO-format
annotations:

```
~/.cache/firewatch/dfire/
├── train/
│   ├── images/  *.jpg
│   └── labels/  *.txt          # one line per box; empty = no fire/smoke
└── test/
    ├── images/
    └── labels/
```

Binary collapse: a non-empty `.txt` → label 1, empty (or missing) → label 0.
Both fire *and* smoke boxes collapse to the positive class; preserving the
distinction is future work (see "Out of scope" in the master plan).

## Outputs

Each run lands in `training/runs/<run_id>/` with:

| File | Content |
|---|---|
| `config.json` | The fully-resolved hyperparams used (YAML + CLI overrides). |
| `last.pt` | State_dict from the latest epoch (for resuming). |
| `best.pt` | State_dict from the epoch with the best val AUROC. |
| `best_metrics.json` | Epoch index + val metrics for the best checkpoint. |
| `events.out.tfevents.*` | TensorBoard scalars (train_loss, val_loss, val_auroc, val_pr_auc, lr). |

View live: `tensorboard --logdir training/runs/`.

## Troubleshooting

**MPS OOM at batch_size=32**: drop to 16. DenseNet121 at 224×224 fp32 is
~28M params + activations; an 8 GB unified-memory M1 can be tight if other
apps are running.

**`num_workers > 0` hangs on macOS**: known torch+multiprocessing flakiness.
Set `data.num_workers: 0` in the YAML or `--num_workers 0` on the CLI.

**Slow first epoch**: PIL JPEG decoding on the data path dominates wall-clock
on Apple Silicon. The model is fast; the bottleneck is image loading.
Increasing `num_workers` helps when it doesn't hang (see above).

**`val_auroc` stuck at 0.0**: the val split likely has only one class. Increase
`val_frac` or check class balance with `python -m training.data.datasets`.

**Want to train a single short run**: `--epochs 2 --max_steps 100 --batch_size 16`
takes ~5 minutes on MPS and is enough to confirm the loss is decreasing.

## Performance target

The first PR ships the pipeline regardless of accuracy — tuning is an
incremental follow-up. Aspirational target on the default config: **val AUROC
≥ 0.85** on the D-Fire test split. Numbers from the actual training run will
land in `docs/MODELS.md` and the v1 checkpoint metadata.
