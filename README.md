# HumoTech — single-camera treadmill gait analysis

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

## Quick start

```bash
# macOS (Apple Silicon) — miniforge installed
bash scripts/setup_mac.sh            # conda env "humotech" (OpenSim 4.6, PyTorch, rtmlib) + tests
# Ubuntu + NVIDIA
bash scripts/setup_ubuntu.sh cu124   # same, with CUDA PyTorch + onnxruntime-gpu

conda activate humotech
humotech check                       # which optional pieces are available
humotech synth --run                 # synthetic treadmill session through the full pipeline
```

Real data:

```bash
# 1. (once per camera/zoom) lens intrinsics from a checkerboard video — recommended
humotech intrinsics checker.mp4 --board 9x6 --square 0.025 --out data/intrinsics.json
# 2. click the 4 belt corners (+ optional extra landmarks) on a frame
humotech calibrate data/S01/trial.mp4 --belt-length 1.60 --belt-width 0.50 \
        --intrinsics data/intrinsics.json --out data/S01/calibration.json
# 3. everything else
humotech run --video data/S01/trial.mp4 --calib data/S01/calibration.json \
        --height 1.78 --mass 72 --out data/S01/results
```

Outputs (`results/`): `summary.json` (means/SD/L-R/symmetry), `strides.csv` (per stride),
`events.json`, `opensim/scaled.osim` + `opensim/ik.mot` (joint angles, open in the OpenSim GUI),
`kp3d_refined.npz`, `plots/events.png`, `plots/joint_angles.png`, `analysis_2d.json`
(2D-only sanity check incl. an independent belt-speed estimate).

## What to record / measure

See **[docs/calibration.md](docs/calibration.md)**. Minimum: belt length & width (the 4 corners
you click), subject height & mass. Strongly recommended, in order of value:

1. **Checkerboard intrinsics** for the camera (focal length + lens distortion) — focal length from
   only 4 coplanar points is the weakest link of the calibration.
2. **One or more off-belt landmarks with known 3D position** (e.g. handrail top at a measured
   height, or a box/pole of known size placed on the belt for one frame).
3. **Force-plate events + the treadmill's displayed speed** for a few trials — the instrumented
   treadmill is the ground truth to validate/tune event detection (`events.hs_offset_ms`, …) and
   the belt-speed estimate.
4. A few seconds of **quiet standing** at the start of each trial (better scaling).

## Layout

```
src/humotech/
  calibration/  camera model, belt-corner calibration (homography → focal, PnP), click tool
  pose2d/       rtmlib / YOLO backends, single-subject tracking, L/R swap fix, filtering
  lift3d/       planar init (CPU), GVHMR/WHAM SMPL adapters, treadmill-constrained refinement
  biomech/      OpenSim scaling, TRC export, IK, forward kinematics of model markers
  gait/         events (Zeni, velocity), belt speed, spatiotemporal parameters
  synth/        synthetic treadmill walker with exact ground truth (tests, demos)
  pipeline.py   end-to-end orchestration with cached intermediates;  cli.py  `humotech …`
opensim_models/ Pose2Sim model + Halpe-26 marker set + IK setup (BSD-3, see LICENSE_Pose2Sim)
configs/        default.yaml — all pipeline options
docs/           calibration.md, method.md, ubuntu_handoff.md
tests/          pytest suite (synthetic ground truth; torch/OpenSim tests auto-skip if missing)
```

## Status (Nov 2026)

| Component | State |
|---|---|
| Calibration (belt corners, focal from homography, PnP, extra landmarks, checkerboard) | implemented, tested on synthetic |
| Click tool for landmarks (OpenCV window) | implemented, needs a manual try on a real frame |
| 2D pose — rtmlib RTMPose Halpe-26 | implemented; model download not testable in the build sandbox → first real run on your machine |
| 2D pose — YOLO-pose | implemented (no feet → degraded) |
| Planar 3D init + treadmill-constrained refinement | implemented, tested (recovers 8 % scale + 12 cm offset errors, belt speed < 3 %) |
| GVHMR / WHAM adapters | written against their public output formats — **verify on Ubuntu** |
| OpenSim scale + IK + FK | implemented, tested with OpenSim 4.6 (conda, Linux) |
| Events, belt speed, spatiotemporal | implemented, tested |
| GUI | not started — planned on Ubuntu (see docs/ubuntu_handoff.md) |

Run the tests with `pytest` (≈30 s). The synthetic walker is kinematically simple, so tests
check the *pipeline* (geometry, bookkeeping, optimisation), not real-world accuracy.
