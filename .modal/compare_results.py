"""Compare Local vs Modal per-frame predictions against ground truth.

Reads the JSON files written by `.modal/run_local.py` and `.modal/run_smoke.py`,
plus `tests/fixtures/trail_cam/ground_truth.json`, and prints a per-clip
report with:
  - detection rate vs ground truth (per path)
  - false-positive rate (per path)
  - Local↔Modal divergence stats (per-frame |Δ fire_probability|)

Usage:
    python .modal/compare_results.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIPS = ["positive_fire", "negative_forest", "mixed_event"]


def _load(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"missing: {path}")
    return json.loads(path.read_text())


def main() -> int:
    gt = json.loads((REPO_ROOT / "tests" / "fixtures" / "trail_cam" / "ground_truth.json").read_text())
    clips_dir = REPO_ROOT / "clips"

    print(f"{'clip':<18}{'frames':>8}{'path':>10}{'detect%':>10}{'fpr%':>8}{'gt_acc%':>10}{'p50_dp':>10}{'p95_dp':>10}{'max_dp':>10}")
    print("-" * 96)

    for clip in CLIPS:
        local = _load(clips_dir / f"local_{clip}_predictions.json")
        modal = _load(clips_dir / f"modal_{clip}_predictions.json")
        truth = gt.get(clip)
        if truth is None:
            sys.exit(f"no ground_truth for {clip}")

        n = min(len(local), len(modal), len(truth))
        for path_name, preds in (("local", local), ("modal", modal)):
            tp = sum(1 for i in range(n) if preds[i]["has_fire"] and truth[i] == 1)
            fp = sum(1 for i in range(n) if preds[i]["has_fire"] and truth[i] == 0)
            pos = sum(1 for i in range(n) if truth[i] == 1)
            neg = n - pos
            correct = sum(1 for i in range(n) if int(preds[i]["has_fire"]) == truth[i])
            detect_pct = (tp / pos * 100) if pos else 0.0
            fpr_pct = (fp / neg * 100) if neg else 0.0
            gt_acc = (correct / n * 100) if n else 0.0
            # Divergence reported on the local row (full pair view); blank on modal.
            if path_name == "local":
                deltas = [abs(local[i]["fire_probability"] - modal[i]["fire_probability"]) for i in range(n)]
                deltas_sorted = sorted(deltas)
                p50 = deltas_sorted[len(deltas_sorted) // 2]
                p95 = deltas_sorted[int(len(deltas_sorted) * 0.95)]
                dmax = max(deltas)
                under_thr = sum(1 for d in deltas if d <= 0.01) / n * 100
                divergence_cols = f"{p50:>10.4f}{p95:>10.4f}{dmax:>10.4f}"
                print(
                    f"{clip:<18}{n:>8}{'local':>10}{detect_pct:>10.1f}{fpr_pct:>8.1f}{gt_acc:>10.1f}{divergence_cols}"
                )
                print(f"{'':<18}{'':>8}{'':>10}{'':>10}{'':>8}{'':>10}  (≤0.01: {under_thr:.1f}% of frames)")
            else:
                print(f"{clip:<18}{n:>8}{'modal':>10}{detect_pct:>10.1f}{fpr_pct:>8.1f}{gt_acc:>10.1f}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
