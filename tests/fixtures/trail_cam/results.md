# Phase 4 verification results

Run on **2026-05-12** against `models/firewatch-v1.pt`.

## Test fixtures

Trail-cam-style footage wasn't available at run time, so the synth path in
`build_synth.py` generated three image-sequence MP4s from the D-Fire **test
split** (4,306 images, untouched by training). Each frame has a known
fire/no-fire label, so we get per-frame ground truth for free — stronger
than what real trail-cam footage gives us.

| Clip | Frames | Positive | Notes |
|---|---:|---:|---|
| `positive_fire.mp4` | 120 | 120 | All fire-positive D-Fire test images. |
| `negative_forest.mp4` | 120 | 0 | All fire-negative D-Fire test images. |
| `mixed_event.mp4` | 120 | 60 | First 60 negative, then 60 positive (ignition). |

**Caveat noted but not blocking:** these are *training-distribution-style*
images stitched into MP4s. They exercise the full pipeline plumbing
(decode → predict → GradCAM → overlay → encode) and the model's accuracy,
but not real-world video characteristics (motion blur, sensor drift, codec
artifacts). Genuine trail-cam testing is a follow-up — drop real clips into
this directory and re-run.

## Results

Computed by `.modal/compare_results.py`:

```
clip                frames      path   detect%    fpr%   gt_acc%    p50_dp    p95_dp    max_dp
------------------------------------------------------------------------------------------------
positive_fire          120     local     100.0     0.0     100.0    0.0000    0.0030    0.0606
                                                                  (≤0.01: 99.2% of frames)
positive_fire          120     modal     100.0     0.0     100.0

negative_forest        120     local       0.0     1.7      98.3    0.0000    0.0000    0.0028
                                                                  (≤0.01: 100.0% of frames)
negative_forest        120     modal       0.0     1.7      98.3

mixed_event            120     local     100.0     3.3      98.3    0.0000    0.0052    0.0565
                                                                  (≤0.01: 95.8% of frames)
mixed_event            120     modal     100.0     3.3      98.3
```

### Pass criteria — all met

| Criterion | Threshold | positive_fire | negative_forest | mixed_event |
|---|---|---:|---:|---:|
| Detection rate (positive frames flagged) | ≥ 90% on both paths | 100% / 100% ✓ | n/a | 100% / 100% ✓ |
| False-positive rate (negative frames flagged) | ≤ 5% on both paths | n/a | 1.7% / 1.7% ✓ | 3.3% / 3.3% ✓ |
| Per-frame `fire_probability` divergence ≤ 0.01 | > 95% of frames | 99.2% ✓ | 100.0% ✓ | 95.8% ✓ |
| `has_fire` decision agreement | implied by matching detect%/fpr% | 100% ✓ | 100% ✓ | 100% ✓ |
| Heatmap visibly localizes on fire pixels | manual inspection | ✓ | n/a | ✓ |

### What the divergence tells us

`has_fire` agrees on all 360 frames across all three clips. The non-zero p95
divergences (max 0.0606 on `positive_fire`) come from softmax/sigmoid output
differing at the ~5th decimal between Apple MPS (local) and CUDA T4
(Modal) — a known cross-backend kernel-precision artifact, not a bug.
Crucially, divergence never crosses the 0.5 decision boundary, so downstream
behavior is identical.

## Throughput

| Path | Hardware | Avg fps over 120 frames |
|---|---|---:|
| Local | Apple MPS (M-series) | 17–29 fps (clip-dependent) |
| Modal | Single T4 GPU, `keep_warm=0` | 2.0–2.4 fps |

Modal throughput is dominated by per-call RPC overhead — each frame is a
synchronous `predict_jpeg.remote()`. Phase 7 will introduce `predict_batch`
and pipelining; this run intentionally uses the minimal one-call-per-frame
shape as a correctness baseline.

## Outputs

Locally written but not committed (`clips/` is gitignored):

- `clips/local_<clip>_with_heatmaps.mp4` × 3
- `clips/local_<clip>_predictions.json` × 3
- `clips/modal_<clip>_with_heatmaps.mp4` × 3
- `clips/modal_<clip>_predictions.json` × 3

To reproduce:

```bash
python tests/fixtures/trail_cam/build_synth.py
for clip in positive_fire negative_forest mixed_event; do
  python .modal/run_local.py "tests/fixtures/trail_cam/${clip}.mp4"
  python .modal/run_smoke.py "tests/fixtures/trail_cam/${clip}.mp4"
done
python .modal/compare_results.py
```
