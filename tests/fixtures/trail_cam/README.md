# Trail-cam smoke-test fixtures

These videos drive the **Phase 4 verification** step — visual confirmation
that `models/firewatch-v1.pt` works on the kind of input the deployed system
will see. They are *not* unit-test fixtures; nothing under `pytest` touches
them.

The MP4 files themselves are gitignored (`*.mp4` in the repo's `.gitignore`).
This README, and the generated `results.md`, are tracked.

## Expected clips

| Filename | Duration | Content |
|---|---|---|
| `positive_fire.mp4` | 5–60 s | Continuous fire footage (visible flames). |
| `negative_forest.mp4` | 5–60 s | Continuous no-fire forest/trail/wilderness clip. |
| `mixed_event.mp4` | 5–60 s | Half no-fire + half fire (state transition). |

### How to source them

Run the bundled fetcher — it downloads two CC0 clips from Pexels and builds
`mixed_event.mp4` by concatenating the first 60 frames of each:

```bash
python tests/fixtures/trail_cam/fetch_real.py
```

Produces all three MP4s plus `ground_truth.json` (per-clip per-frame labels)
in this directory. Sources are listed in the script docstring.

If you have your own footage, just drop the three named MP4s in this
directory and skip `fetch_real.py`; the runners don't care where the clips
came from. Re-running `fetch_real.py` against existing files is a no-op for
the downloads but always rebuilds `mixed_event.mp4` + `ground_truth.json`,
so delete those two if you bring your own and want to skip the concat step.

## Verification workflow

After clips are in place, run both paths (no Kafka required — the Kafka
transport is independently covered by the unit suite) and write results to
`results.md`:

```bash
# Warm test — confirms the Modal container builds and predict round-trips.
modal run .modal/firewatch_smoke.py

# Per-clip annotated MP4s + predictions JSON, both paths.
for clip in positive_fire negative_forest mixed_event; do
  [ -f "tests/fixtures/trail_cam/${clip}.mp4" ] || continue
  python3 .modal/run_local.py "tests/fixtures/trail_cam/${clip}.mp4"
  python3 .modal/run_smoke.py "tests/fixtures/trail_cam/${clip}.mp4"
done
# Output → clips/{local,modal}_<clip>_with_heatmaps.mp4
#          clips/{local,modal}_<clip>_predictions.json

# Compute Local↔Modal divergence and ground-truth accuracy.
python3 .modal/compare_results.py
```

If you also want to exercise the full Kafka path on these clips:

```bash
docker-compose up -d && ./scripts/setup_kafka_topics.sh
ML_MODEL_TYPE=firewatch FIREWATCH_MODEL_PATH=models/firewatch-v1.pt python3 -m streams &
python3 -m producer "tests/fixtures/trail_cam/positive_fire.mp4" "kafka_positive_fire"
```

## Pass criteria

Recorded in `results.md`:

| Clip | Metric | Threshold |
|---|---|---|
| `positive_fire.mp4` | Fire-frame detection rate | ≥ 90% on both Local and Modal |
| `negative_forest.mp4` | False-positive rate | ≤ 5% on both Local and Modal |
| any clip | Per-frame `fire_probability` Local vs Modal divergence | ≤ 0.01 on > 95% of frames |
| any clip | Heatmap visibly localizes on flame pixels | Manual inspection of annotated MP4 |

A clip is considered to "have fire" in a given frame if `fire_probability ≥
CONFIDENCE_THRESHOLD` (default 0.5).
