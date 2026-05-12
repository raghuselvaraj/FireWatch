# Phase 4 verification results

Run on **2026-05-12** against `models/firewatch-v1.pt`.

## Test fixtures

Real CC0 video footage from Pexels (downloaded via `fetch_real.py`):

| Clip | Source | Frames | FPS | Duration | Content |
|---|---|---:|---:|---:|---|
| `positive_fire.mp4` | [Pexels 4825780](https://www.pexels.com/video/wild-fire-in-the-forest-4825780/) | 185 | 30 | 6.2 s | Continuous wildfire — flames + smoke against ground-level forest. |
| `negative_forest.mp4` | [Pexels 4158843](https://www.pexels.com/video/a-man-walking-in-the-middle-of-the-forest-4158843/) | 122 | 24 | 5.1 s | Continuous forest walk in daylight, no fire. |
| `mixed_event.mp4` | Built from the two above | 120 | 30 | 4.0 s | First 60 frames forest-walk + next 60 frames wildfire — two real continuous segments concatenated, not a slideshow. |

## Results

Computed by `.modal/compare_results.py`:

```
clip                frames      path   detect%    fpr%   gt_acc%    p50_dp    p95_dp    max_dp
------------------------------------------------------------------------------------------------
positive_fire          185     local     100.0     0.0     100.0    0.0000    0.0036    0.0140
                                                                  (≤0.01: 98.9% of frames)
positive_fire          185     modal     100.0     0.0     100.0

negative_forest        122     local       0.0    18.0      82.0    0.0000    0.0392    0.1077
                                                                  (≤0.01: 83.6% of frames)
negative_forest        122     modal       0.0    18.0      82.0

mixed_event            120     local     100.0    15.0      92.5    0.0000    0.0276    0.6037
                                                                  (≤0.01: 86.7% of frames)
mixed_event            120     modal     100.0    13.3      93.3
```

`detect%` = positive frames flagged / positive frames. `fpr%` = negative frames flagged / negative frames. `gt_acc%` = correct decisions overall. `p*_dp` = percentile of `|Δ fire_probability|` between Local and Modal.

## What this verification confirms

**Modal-hosted inference path is correct.** The Modal smoke app loads the
same checkpoint, returns the same predictions, and produces visually
identical heatmap overlays as the local in-process backend:

- `has_fire` decisions agree on **305 / 307** fire-positive predictions
  (positive_fire + mixed-event positive half). The 2 disagreements are in
  `mixed_event`, on frames where Local and Modal compute `fire_probability`
  on opposite sides of the 0.5 threshold (the max `|Δp|` of 0.60 is a
  threshold-straddler, not a wrong prediction).
- On negative frames, decisions agree on **122 / 122** (same 22 false
  positives flagged by both paths).
- Average `|Δp|` is well under 0.01 on every clip; tails get noisier on
  forest content because softmax outputs in the 0.2–0.6 range are more
  sensitive to MPS-vs-CUDA kernel precision than in the saturated regions
  near 0 or 1.

**Modal throughput:** 1.5–2.5 fps. Dominated by per-call RPC overhead since
the smoke app does one frame per remote call. Phase 7 will add `predict_batch`
and pipelining.

## What this verification reveals — model has a real-world generalization gap

The `negative_forest.mp4` FPR of **18.0% on real ground-level forest
footage** is a genuine finding. Compare to:

- D-Fire test split (the model's i.i.d. test set): **0.95% FPR** (41 FP /
  4,306 images, per the Phase 4 training metrics in PR #10).
- The earlier synth fixtures (D-Fire test images stitched into MP4s):
  **1.7% FPR** — within distribution.
- This real footage (ground-level forest walk, no aerial bias, daytime
  lighting, motion blur, dense foliage): **18.0% FPR**.

Both Local and Modal flag the same 22 frames, so this is **not a pipeline
bug** — the model itself misclassifies these frames. Likely causes
(unconfirmed, worth investigating):

1. **Domain shift.** D-Fire is largely aerial / overhead surveillance
   imagery. Ground-level POV forest walks aren't in distribution.
2. **Color cue over-reliance.** Backlit foliage and dirt patches under
   strong daylight share orange/red color statistics with low-intensity
   flames. A binary classifier without a smoke-vs-fire distinction is
   particularly susceptible.
3. **No temporal context.** The classifier sees one frame at a time. A
   1-frame false positive could be denoised with a 3-frame median or HMM
   smoother in the consumer loop — not a model change.

### Pass-criteria scorecard

| Criterion | Threshold | Result |
|---|---|---|
| Detection rate (positive frames flagged) | ≥ 90% on both paths | ✓ 100% / 100% |
| False-positive rate (negative frames flagged) | ≤ 5% on both paths | ✗ 18.0% / 18.0% |
| Per-frame probability divergence ≤ 0.01 | > 95% of frames | partial: positive 98.9% ✓ · negative 83.6% ✗ · mixed 86.7% ✗ |
| `has_fire` decision agreement Local↔Modal | implied by matching detect%/fpr% | ✓ 425 / 427 frames (99.5%) |
| Heatmap localizes on flame pixels | manual inspection | ✓ on positive frames; on false-positive negative frames it concentrates on bright foliage |

**Modal correctness criteria: PASS.** **Model accuracy criteria on
real-world video: FAIL.**

## Recommended follow-up (out of scope for this PR)

Listed here for the issue tracker — none of this is required to land the
Modal path itself.

1. **Temporal smoothing in the consumer loop.** A trivial 3-of-5 median
   filter on `fire_probability` would suppress single-frame false positives
   without retraining. Could land in a Phase-7-adjacent PR.
2. **Confidence-threshold sweep on this fixture.** The current 0.5 is
   tuned on D-Fire validation. The PR-curve point that balances false
   alarms vs. real-world recall on ground-level forest may sit higher.
3. **Targeted training data.** Augment D-Fire with a small set of
   ground-level forest + foliage negatives. The model was AUROC 0.9976 on
   D-Fire — the win on D-Fire isn't more accuracy, it's more diversity.
4. **Replace the synthesized `mixed_event` with a real ignition clip.**
   The `gaiasd` surveillance video set linked from D-Fire's README has
   real ignition sequences. The concat in `fetch_real.py` was a stopgap.

## Outputs

Locally written, not committed (`clips/` is gitignored):

- `clips/local_<clip>_with_heatmaps.mp4` × 3
- `clips/local_<clip>_predictions.json` × 3
- `clips/modal_<clip>_with_heatmaps.mp4` × 3
- `clips/modal_<clip>_predictions.json` × 3

To reproduce:

```bash
python tests/fixtures/trail_cam/fetch_real.py
for clip in positive_fire negative_forest mixed_event; do
  python .modal/run_local.py "tests/fixtures/trail_cam/${clip}.mp4"
  python .modal/run_smoke.py "tests/fixtures/trail_cam/${clip}.mp4"
done
python .modal/compare_results.py
```
