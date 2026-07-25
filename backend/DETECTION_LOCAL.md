# Testing bird detection on your Mac webcam

Two ways to run the detection model locally against the built-in webcam.

## One-time setup

Install the optional detection dependencies (ultralytics + **CPU-only** torch —
no CUDA) into the project venv, from the `backend/` directory:

```bash
cd backend
uv sync --group detection
```

The first detection run also downloads the model weights (`yolo11n.pt`, ~5 MB),
so you need internet access that first time.

macOS will prompt for **camera permission** the first time capture starts. If it
fails, grant access under *System Settings → Privacy & Security → Camera* for
your terminal app, then re-run.

## Option A — Live preview window (recommended)

A standalone runner opens the webcam, runs the model, and serves an annotated
live view (boxes + labels + FPS) in your browser.

```bash
make detect-webcam
# then open http://localhost:8060
```

By default it detects **all** object classes, so you can confirm it works at your
desk without a real bird in frame. Useful variations:

```bash
make detect-webcam ARGS="--classes bird"        # birds only (production behavior)
make detect-webcam ARGS="--source 1"            # a different camera
make detect-webcam ARGS="--conf 0.3"            # lower confidence threshold
make detect-webcam ARGS="--model yolo11s.pt"    # a larger/more accurate model
```

Or run it directly:

```bash
cd backend
uv run --group detection python scripts/detect_webcam.py
```

Press `Ctrl-C` in the terminal to stop. Config flags mirror the app's
`DETECTION_*` environment variables (see the script header for the full list).

## Option B — The full backend app, webcam as source

Runs the real backend with its detection worker reading the webcam. Detections
are exposed as JSON (no boxes drawn) at the `/detection/*` endpoints.

1. Add these to `backend/.env` (local overrides):

   ```dotenv
   DETECTION_ENABLED=true
   DETECTION_STREAM_URL=0        # 0 = default webcam device index
   DETECTION_CLASSES=            # empty = all classes; default is "bird,cat"
   DETECTION_MOTION_GATE=false   # infer every sampled frame (a still desk scene
                                 # otherwise gets gated out as "no motion")
   DETECTION_SPECIES_ENABLED=true  # optional: classify bird species on crops
   ```

   With species classification on, each detected bird is cropped and run
   through a 525-species classifier (~30 MB, downloaded from Hugging Face on
   first run). Detections gain `"species"` and `"species_confidence"` fields
   when the classifier is confident (`DETECTION_SPECIES_CONF`, default 0.5);
   otherwise the plain `"bird"` label stands. A phone photo of a bird held up
   to the webcam is an easy way to test.

2. Start the backend:

   ```bash
   uv sync --group detection     # once, if not already done
   make dev-backend
   ```

3. Inspect results:

   ```bash
   curl localhost:8051/detection/status    # worker + camera status
   curl localhost:8051/detection/latest    # detections on the most recent frame
   curl localhost:8051/detection/events    # recent frames that contained a match
   ```

`DETECTION_STREAM_URL=0` opens the local camera device index; any non-numeric
value is still treated as a stream URL (RTSP), so production is unaffected.

## Troubleshooting

- **`ultralytics is not installed`** — run `uv sync --group detection` in
  `backend/` first (Option A's `make` target does this for you).
- **Camera won't open** — grant camera permission (above), or try `--source 1`.
- **`uv` can't find a torch wheel for Python 3.14** — the project pins
  `requires-python = ">=3.14"`. If torch has no macOS CPU wheel for 3.14 yet,
  either temporarily set `requires-python = ">=3.12"` in `backend/pyproject.toml`
  and re-run, or test in a throwaway venv decoupled from the project:

  ```bash
  cd backend
  python3.12 -m venv .venv-detect
  . .venv-detect/bin/activate
  pip install ultralytics opencv-python-headless
  python scripts/detect_webcam.py
  ```
