# Trail-cam smoke-test fixtures

These videos drive the **Phase 4 verification** step — visual confirmation
that `models/firewatch-v1.pt` works on the kind of input the deployed system
will see. They are *not* unit-test fixtures; nothing under `pytest` touches
them.

The MP4 files themselves are gitignored (`*.mp4` in the repo's `.gitignore`).
This README, and the generated `results.md`, are tracked.

## Expected clips

Place these files here before running the verification:

| Filename | Duration | Content |
|---|---|---|
| `positive_fire.mp4` | 10–60 s | Trail-cam-style fire footage (visible flames, ideally with surrounding forest/structure). |
| `negative_forest.mp4` | 10–60 s | No-fire forest, trail, or wilderness clip. Daylight; ideally similar lighting to `positive_fire.mp4`. |
| `mixed_event.mp4` *(optional)* | 30–60 s | Single clip that transitions from no-fire to fire (ignition event). |

### Where to source them

- Personal trail-cam footage if available — preferred for realism.
- CC0 stock: search Pexels / Pixabay for "forest fire", "wildfire", "campfire".
- The D-Fire dataset's README links to `gaiasd`'s surveillance video set; those
  are good `mixed_event` candidates.

### Fallback: synthesize from D-Fire test images

If no real footage is available, `build_synth.py` stitches the three clips
from the D-Fire test split (each frame has a known label, so ground truth
falls out for free). Run from the repo root:

```bash
python tests/fixtures/trail_cam/build_synth.py
```

Produces the three MP4s above plus `ground_truth.json` (per-clip per-frame
labels) in this directory. Note these are *training-distribution* images
rather than trail-cam-style footage — they exercise the pipeline correctly
but don't stress real-world video characteristics. Used for the initial
Phase 4 verification run; see `results.md`.

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
