#!/usr/bin/env bash
# Install GVHMR (world-grounded SMPL-X video lifter) in its OWN conda env, next to humotech.
# Follow https://github.com/zju3dv/GVHMR/blob/main/docs/INSTALL.md if anything here drifts.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p third_party && cd third_party
[ -d GVHMR ] || git clone --recursive https://github.com/zju3dv/GVHMR
cd GVHMR
conda create -y -n gvhmr python=3.10 || true
conda run -n gvhmr python -m pip install -r requirements.txt
conda run -n gvhmr python -m pip install -e .
cat <<MSG

Next (manual, needs registration):
  1. Download SMPL + SMPL-X body models (smpl.is.tue.mpg.de, smpl-x.is.tue.mpg.de) into
     third_party/GVHMR/inputs/checkpoints/body_models/{smpl,smplx}
     and ALSO point humotech's lift.smpl_model_dir to that body_models folder.
  2. Download the GVHMR checkpoints (gvhmr, hmr2, vitpose, yolo, dpvo) listed in their INSTALL.md
     into third_party/GVHMR/inputs/checkpoints/
  3. Run on a treadmill video (static camera -> -s):
       conda run -n gvhmr python tools/demo/demo.py --video=/path/to/trial.mp4 -s
     then in humotech's config:  lift: {backend: gvhmr, result_path: .../hmr4d_results.pt, smpl_model_dir: ...}
MSG
