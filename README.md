# HumoTech: single-camera treadmill gait analysis

One video of a person walking on a treadmill → OpenSim-constrained joint kinematics →
gait events → spatiotemporal parameters (stride frequency, stride/step length, stance %, …),
with the **belt speed estimated from the stance foot** (no treadmill speed needed).

```
video ─► 2D pose (RTMPose Halpe-26: body + heels/toes)
      ─► 3D lift (planar back-projection on CPU | GVHMR / WHAM on GPU)
      ─► treadmill-constrained refinement (PyTorch)           ◄── camera calibration
           reprojection · constant bones · stance foot moves at −v_belt on the belt plane
      ─► OpenSim: scale model + inverse kinematics (Pose2Sim full-body model)
      ─► gait events (Zeni / velocity) ─► spatiotemporal parameters + belt speed
```

Background on each stage: [docs/method.md](docs/method.md). Recording protocol and what to
measure: [docs/calibration.md](docs/calibration.md).

---

## 1. Installation

Requires [miniforge](https://github.com/conda-forge/miniforge) (conda). OpenSim's Python bindings
only install cleanly through conda, so pip-only environments are not supported.

```bash
# macOS (Apple Silicon)
bash scripts/setup_mac.sh            # conda env "humotech" (OpenSim 4.6, PyTorch, rtmlib) + runs the tests
# Ubuntu + NVIDIA
bash scripts/setup_ubuntu.sh cu124   # same, with CUDA PyTorch + onnxruntime-gpu

conda activate humotech
humotech check                       # lists which optional pieces are importable
```

Or install by hand into an existing conda env:

```bash
conda env create -f environment.yml          # or: conda install -c opensim-org opensim
pip install -e ".[pose,refine,app,dev]"      # extras: pose | yolo | refine | gpu3d | app | dev
```

| Extra | Provides | Needed for |
|---|---|---|
| `pose` | rtmlib + onnxruntime | 2D pose (RTMPose Halpe-26, recommended) |
| `yolo` | ultralytics | YOLO-pose fallback (no foot keypoints, so results are degraded) |
| `refine` | torch | treadmill-constrained 3D refinement |
| `gpu3d` | torch + smplx | GVHMR / WHAM lifters (Ubuntu + NVIDIA, see `scripts/install_gvhmr.sh`) |
| `app` | fastapi + uvicorn | the web app (`humotech app`) |
| `dev` | pytest, ruff, httpx | tests, linting |

Optional: `bash scripts/fetch_opensim_geometry.sh` downloads the bone meshes so the model renders
in the OpenSim GUI (not needed for the analysis).

## 2. Web app

Everything below can be done from a browser UI instead of the command line: create subjects,
add videos, calibrate the camera and the belt, process trials in the background and browse the
results.

```bash
conda activate humotech
humotech app                          # opens http://localhost:8000, data folder ./data
humotech app --data /path/to/data --port 8080 --no-browser
humotech app --host 0.0.0.0           # reachable from other machines on the network (no login, trusted LAN only)
```

| Page | What it does |
|---|---|
| **Subjects** | one card per subject folder in `data/`; progress of each |
| **Subject** | 4-step checklist (details → camera → belt → process), trial table with live status and key results, drag-and-drop video upload, video roles (trial / checkerboard) |
| **Belt calibration** | pick a frame, click the 4 belt corners (magnifier, drag to adjust, arrow keys to nudge, warning if two corners look swapped), add measured off-belt points, solve; shows per-point error and the grid overlay |
| **Results** | belt speed vs treadmill, parameter table (mean ± SD, L/R, symmetry, CV), joint angles over the gait cycle, stride-by-stride chart, video review with 2D keypoints and the detected events, downloads |
| **Cameras** | checkerboard intrinsics (runs `humotech intrinsics`), quality and which subjects use them |
| **Jobs** | queue of background runs (one at a time), live log and progress, cancel |
| **System** | installed packages, GPU / CUDA readiness, self-test on synthetic data |

How it fits together:

* The app works on the same folder layout as the CLI: `data/<subject>/` holds the videos,
  `calibration.json`, and `subject.json` (height, mass, chosen intrinsics). Results go to
  `data/<subject>/results/<trial>/`. Videos copied or symlinked into a subject folder show up
  without uploading.
* Processing runs `humotech run` as a subprocess per trial, so the server stays up if a run
  crashes, and logs are kept in `data/.jobs/`. The settings chosen in the dialog are saved next to
  the results (`run_config.yaml`, `run.json`).
* The treadmill speed entered when processing (pre-filled from names like `1p2mps_walk`) is
  only used to check the estimate, unless you choose "Use treadmill speed".

## 3. Sanity check on synthetic data

```bash
humotech synth --run                 # writes data/synthetic/ and runs the full pipeline on it
```

This generates a treadmill walker with exact ground truth (1.2 m/s belt, 1.1 s stride) and prints
the recovered parameters next to the truth. A committed reference run is in
[data/synthetic/results/](data/synthetic/results/). For example:

| | ground truth | recovered |
|---|---|---|
| belt speed (m/s) | 1.20 | 1.202 |
| stride time (s) | 1.10 | 1.100 |
| stride length (m) | 1.32 | 1.318 |
| step length (m) | 0.66 | 0.659 |
| step width (m) | 0.13 | 0.123 |

The synthetic walker is kinematically simple, so this checks the *pipeline* (geometry,
bookkeeping, optimisation), not real-world accuracy.

## 4. Processing a real session

Session data lives in `data/<subject>/` (see [data/README.md](data/README.md)). Videos are
git-ignored; calibration JSONs and results can be committed.

### 4.1 Lens intrinsics (once per camera + zoom setting)

Record a short video of a printed checkerboard held at many positions and angles (fill the corners
of the frame too, and tilt the board ±30–45°), **with the same camera, resolution, zoom and focus as
the trials**. Then:

```bash
humotech intrinsics data/S01/intrinsic.mov --board 7x4 --square 0.04 --step 20 \
        --out data/intrinsics.json
```

That is the exact command used for the current [data/intrinsics.json](data/intrinsics.json).

| Option | Meaning |
|---|---|
| `--board CxR` | **inner** corners (columns × rows), not squares. A board with 8 × 5 squares is `7x4`. |
| `--square` | edge length of one square in metres (measure the print, don't trust the PDF) |
| `--step N` | use every N-th frame. Larger is faster and gives less-correlated views. At least 8 frames must detect the board. |
| `--out` | output JSON: `K` (3×3), `dist` (k1 k2 p1 p2 k3), `image_size` (width, height), `rms_px` |

Check `rms_px` in the output: below ~0.5 px is good, above ~1 px usually means blur, a wrong
`--board`/`--square`, or too few distinct views. The current file is from a portrait 1080×1920 video:
fx ≈ fy ≈ 1760 px, RMS 0.35 px.

If you change camera, resolution, orientation or zoom, redo this step. The intrinsics `image_size`
must match the trial videos.

### 4.2 Extrinsics: click the belt (once per camera placement)

```bash
humotech calibrate data/S01/trial.mp4 --belt-length 1.60 --belt-width 0.50 \
        --intrinsics data/intrinsics.json --out data/S01/calibration.json
        # optional: --extra data/S01/extra_landmarks.yaml  --frame 120
```

Click the four belt corners in the order shown on screen (`belt_front_left, belt_front_right,
belt_back_right, belt_back_left`; *front* = the end the subject faces, left/right = the
**subject's**). `u` undoes, `s` skips an optional extra landmark, Enter accepts. The command prints
per-landmark reprojection errors and writes `calibration.png` next to the JSON: the 10 cm grid
must sit on the belt and the green posts are 1 m tall. Errors above 2–3 px usually mean a
mis-click or wrong belt dimensions. Details and the `--extra` YAML format:
[docs/calibration.md](docs/calibration.md#clicking-humotech-calibrate).

### 4.3 Run the pipeline

```bash
humotech run --video data/S01/trial.mp4 --calib data/S01/calibration.json \
        --height 1.78 --mass 72 --out data/S01/results
```

| Option | Meaning |
|---|---|
| `--video` / `--kp2d` | input video, or an existing `kp2d_raw.npz` to skip 2D detection |
| `--calib` | `calibration.json` from step 4.2 (required) |
| `--height`, `--mass` | subject height (m) and mass (kg); override the config |
| `--config` | YAML overriding [configs/default.yaml](configs/default.yaml) |
| `--device` | `cpu` / `cuda` / `mps`, used for pose and refinement |
| `--force` | recompute everything instead of reusing cached intermediates in `--out` |

Intermediates are cached in the output folder, so re-running after a config change only redoes
the affected stages. `humotech detect video.mp4 --out kp2d_raw.npz` runs only the 2D pose stage.

### 4.4 Outputs (`results/`)

| File | Content |
|---|---|
| `summary.json` | per-parameter mean / SD / L / R / CV % / symmetry index, belt speed, stride counts |
| `strides.csv` | one row per stride |
| `events.json` | heel-strike and toe-off times per foot |
| `opensim/scaled.osim`, `opensim/ik.mot` | scaled model + joint angles (open in the OpenSim GUI) |
| `kp3d_refined.npz`, `refine_info.json` | refined 3D keypoints in the treadmill frame + optimiser report |
| `analysis_2d.json` | 2D-only sanity check, including an independent belt-speed estimate |
| `plots/events.png`, `plots/joint_angles.png` | quick-look figures |
| `config_used.yaml` | the exact configuration of this run |

Coordinate frame (= OpenSim ground): origin at the belt centre, **+X forward**, **+Y up**
(belt is Y = 0), **+Z subject's right**.

## 5. Configuration

All options are in [configs/default.yaml](configs/default.yaml); copy it per session and pass
`--config`. The ones most often changed:

| Key | Default | Notes |
|---|---|---|
| `pose2d.backend` / `mode` | `rtmlib` / `balanced` | `performance` is more accurate, slower |
| `lift.backend` | `planar` | `gvhmr` / `wham` need their result file in `lift.result_path` (GPU) |
| `refine.device` | `cpu` | `cuda` on Ubuntu |
| `events.method` / `source` | `zeni` / `opensim` | `velocity`; `refined` or `2d` if OpenSim is unavailable |
| `events.hs_offset_ms`, `to_offset_ms` | 0 | constant corrections learned against force plates |
| `belt_speed.source` | `refined` | set `known` + `known_m_s` to use the treadmill's displayed speed |

## 6. What to record / measure

See **[docs/calibration.md](docs/calibration.md)**. Minimum: belt length & width (the 4 corners
you click), subject height & mass. Strongly recommended, in order of value:

1. **Checkerboard intrinsics** for the camera (focal length + lens distortion). Focal length from
   only 4 coplanar points is the weakest link of the calibration. (Done for S01, see 4.1.)
2. **One or more off-belt landmarks with known 3D position** (e.g. handrail top at a measured
   height, or a box/pole of known size placed on the belt for one frame).
3. **Force-plate events + the treadmill's displayed speed** for a few trials. The instrumented
   treadmill is the ground truth to validate/tune event detection (`events.hs_offset_ms`, …) and
   the belt-speed estimate.
4. A few seconds of **quiet standing** at the start of each trial (better scaling).

Camera: static tripod, side-on, mounted above hip height and tilted down, ≥ 60 fps, short shutter,
focus/zoom/exposure locked, stabilisation off.

## 7. Repository layout

```
src/humotech/
  calibration/  camera model, belt-corner calibration (homography → focal, PnP), checkerboard, click tool
  pose2d/       rtmlib / YOLO backends, single-subject tracking, L/R swap fix, filtering
  lift3d/       planar init (CPU), GVHMR/WHAM SMPL adapters, treadmill-constrained refinement
  biomech/      OpenSim scaling, TRC export, IK, forward kinematics of model markers
  gait/         events (Zeni, velocity), belt speed, spatiotemporal parameters
  synth/        synthetic treadmill walker with exact ground truth (tests, demos)
  io/           video frame iteration, keypoint containers
  app/          web app: FastAPI server, job runner, static UI (no build step, no CDN)
  pipeline.py   end-to-end orchestration with cached intermediates
  cli.py        `humotech …` commands: app, check, synth, intrinsics, calibrate, detect, run
opensim_models/ Pose2Sim model + Halpe-26 marker set + IK/scaling setups (BSD-3, see LICENSE_Pose2Sim)
configs/        default.yaml: all pipeline options
data/           intrinsics.json, per-subject sessions, synthetic reference run
docs/           calibration.md, method.md, ubuntu_handoff.md
scripts/        setup_mac.sh, setup_ubuntu.sh, install_gvhmr.sh, fetch_opensim_geometry.sh
tests/          pytest suite (synthetic ground truth; torch/OpenSim tests auto-skip if missing)
```

## 8. Tests

```bash
pytest                    # ≈30 s; torch / OpenSim tests skip automatically if those aren't installed
pytest -m "not opensim"   # markers: opensim, torch, slow
```

## 9. Status (Nov 2026)

| Component | State |
|---|---|
| Checkerboard intrinsics | implemented; **run on real data** (S01, RMS 0.35 px) |
| Belt-corner calibration (focal from homography, PnP, extra landmarks) | implemented, tested on synthetic |
| Click tool for landmarks | in the web app; the OpenCV window (`humotech calibrate`) remains for the CLI |
| 2D pose: rtmlib RTMPose Halpe-26 | implemented; first real run pending |
| 2D pose: YOLO-pose | implemented (no feet, so degraded) |
| Planar 3D init + treadmill-constrained refinement | implemented, tested (recovers 8 % scale + 12 cm offset errors, belt speed < 3 %) |
| GVHMR / WHAM adapters | written against their public output formats; **verify on Ubuntu** |
| OpenSim scale + IK + FK | implemented, tested with OpenSim 4.6 (conda, Linux) |
| Events, belt speed, spatiotemporal | implemented, tested; synthetic reference run committed |
| Web app | implemented; API + job runner tested; checked against S01 (frames, calibration, intrinsics job) on the Mac. **First full GPU run from the app pending on Ubuntu** |

Verified so far: full suite (22 tests) with OpenSim 4.6 + PyTorch 2.x CPU on Linux x86_64 (same
conda env as `environment.yml`); core tests (no torch/OpenSim) in a Linux VM on the Mac;
`humotech intrinsics` on a real checkerboard video. `scripts/setup_mac.sh` on native macOS has not
been confirmed yet.

## 10. Troubleshooting

* **`Only N usable checkerboard views; need >= 8`**: check `--board` counts *inner* corners;
  lower `--step`; make sure the whole board is visible and sharp in many frames.
* **High calibration reprojection error**: corners clicked in the wrong order (left/right are the
  subject's), wrong belt dimensions, or intrinsics from a different resolution/orientation/zoom.
* **`humotech check` shows `opensim` missing**: OpenSim must come from conda
  (`conda install -c opensim-org opensim`), not pip. Without it, set `opensim.enabled: false` and
  `events.source: refined`.
* **Left/right legs swapped in places**: `clean.fix_lr_swaps` is on by default; a more side-on
  camera and contrasting shoes help.
