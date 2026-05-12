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

## Verification workflow

After the three (or two) clips are in place, run both paths and write results
to `results.md`:

### Local pipeline

```bash
docker-compose up -d && ./scripts/setup_kafka_topics.sh
ML_MODEL_TYPE=firewatch FIREWATCH_MODEL_PATH=models/firewatch-v1.pt python3 -m streams &
for clip in positive_fire negative_forest mixed_event; do
  [ -f "tests/fixtures/trail_cam/${clip}.mp4" ] || continue
  python3 -m producer "tests/fixtures/trail_cam/${clip}.mp4" "local_${clip}"
done
# Output → clips/local_<clip>_with_heatmaps.mp4
```

### Modal smoke path

```bash
# Warm test — confirms the container builds, model loads, predict round-trips.
modal run .modal/firewatch_smoke.py

# Per-clip annotated MP4s + predictions JSON.
for clip in positive_fire negative_forest mixed_event; do
  [ -f "tests/fixtures/trail_cam/${clip}.mp4" ] || continue
  python3 .modal/run_smoke.py "tests/fixtures/trail_cam/${clip}.mp4"
done
# Output → clips/modal_<clip>_with_heatmaps.mp4
#          clips/modal_<clip>_predictions.json
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
