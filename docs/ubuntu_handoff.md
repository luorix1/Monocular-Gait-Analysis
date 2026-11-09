# Ubuntu (NVIDIA) hand-off

```bash
git clone <your repo> HumoTech && cd HumoTech
bash scripts/setup_ubuntu.sh cu124      # env + CUDA torch + onnxruntime-gpu, runs tests
conda activate humotech && humotech check   # torch cuda=True, CUDAExecutionProvider listed
```
Set `pose2d.device: cuda` and `refine.device: cuda` in your config.

## To verify first (could not be exercised on the Mac build sandbox)
1. **rtmlib model download + output** on a real video: `humotech detect trial.mp4`. Check the
   confidence scaling in `pose2d/detect.py` (raw SimCC scores are squashed to [0,1] heuristically)
   and that heels/toes are sensible.
2. **Calibration click tool** on a real frame; inspect the preview PNG.
3. **GVHMR**: `bash scripts/install_gvhmr.sh`, run its demo with `-s`, then
   `lift: {backend: gvhmr, result_path: .../hmr4d_results.pt, smpl_model_dir: .../body_models}`.
   `lift3d/smpl_lifters.py` was written against the documented output keys — confirm
   `smpl_params_incam` exists and SMPL-X joint/vertex mapping looks right (plot kp3d_init).
4. **Validation vs. instrumented treadmill**: export force-plate HS/TO + belt speed, compare with
   `gait.analysis.compare_events`; set event offsets in the config.

## Suggested next steps
* GUI (Ubuntu): PySide6/Qt app — video player with keypoint overlay; calibration clicking with
  zoom; run pipeline with progress; plots (events, joint angles, belt speed per stance); export.
  Alternatively a local web UI (FastAPI + React) if remote use matters.
* Batch processing of sessions (`data/<subject>/<trial>`), a results database/CSV roll-up.
* Optional belt-texture optical flow as an independent belt-speed check.
* Better synthetic data: drive the OpenSim model with normative gait curves and render markers,
  for anatomically realistic tests.
* Event detection learned from force-plate labels (the instrumented treadmill gives unlimited
  labels).
