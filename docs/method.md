# Method notes

## 1. Calibration
Belt corners (known L × W, on Y = 0) give a plane→image homography H. With square pixels, zero
skew and the principal point at the image centre, orthonormality of the first two rotation
columns gives two equations linear in 1/f² (Zhang 2000) → focal length. Pose from planar PnP
(IPPE), then joint Levenberg–Marquardt refinement of (f, R, t) over all landmarks. With checkerboard
intrinsics, K and distortion are fixed and only the pose is solved.

## 2. 2D pose
RTMPose "BodyWithFeet" (Halpe-26) via `rtmlib` (ONNX Runtime; CPU on Mac, CUDA on Ubuntu). Feet
keypoints (heel, big toe, small toe) are essential for events and belt speed — COCO-17 models
(YOLO-pose) lack them. Post-processing: single-subject tracking, L/R leg-label swap correction
(common for the far leg in side views), spline gap filling, 8 Hz zero-lag Butterworth.

Possible upgrades: RTMW / Sapiens / ViTPose-H whole-body on GPU; fine-tuning on treadmill frames.

## 3. 3D lift
* `planar` (CPU): each keypoint back-projected onto a sagittal plane Z = ±w (w from anthropometry).
* `gvhmr` / `wham` (GPU): SMPL(-X) body pose from video; we keep only the **root-relative** pose
  (rotated into the treadmill frame with the calibrated R) and discard their global trajectory —
  their world-grounding assumes static feet in contact, which is wrong on a moving belt (the same
  reason OpenCap Monocular lists treadmill walking as unsupported).

## 4. Treadmill-constrained refinement (`lift3d/refine.py`)
Variables: X(t) for all keypoints (= lift + global offset + per-frame root offset + per-joint
residual, plus a global size factor), constant bone lengths (L/R shared), belt speed v, stance
sole heights. Minimise (each term divided by a noise σ):

| term | meaning |
|---|---|
| reprojection (Huber, confidence-weighted) | X projects on the 2D keypoints through the calibrated camera |
| bone length | segment lengths constant in time |
| contact velocity | in flat-foot stance, heel/toes/ankle velocity = (−v, 0, 0) |
| contact height | in stance, heel/toe at a constant sole height above the belt (prior 3 / 2 cm) |
| penetration | feet above Y = 0 |
| smoothness | small accelerations |
| prior | weak pull to the lift |

Stance windows: Zeni events on the current estimate, 10–80 % of stance; re-detected each round.
The contact-height term is what fixes monocular depth/scale; it trades off against the sole-height
prior, hence the recommendation of a downward-tilted camera.

Inspired by OpenCap Monocular (Miller et al. 2026, arXiv 2603.24733: WHAM + optimisation +
OpenSim) and SKEL/WHAM-style physically plausible fitting, adapted to the moving belt.

## 5. OpenSim
Pose2Sim full-body model (40 DoF incl. lumbar, neck, arms; BSD-3) with the Halpe-26 marker set.
Scaling: uniform per-body factors from median refined segment lengths (walking trials make
OpenSim's averaged-marker measurement scaling unreliable). IK with Pose2Sim marker weights.
Model markers are then re-computed by forward kinematics (“OpenSim-constrained keypoints”) and
used for events.

## 6. Events
* **Zeni** (default): HS = max(heel_x − pelvis_x), TO = min(toe_x − pelvis_x). Known systematic
  offsets of tens of ms (HS early when the foot retracts before contact, TO late) — calibrate
  against force plates and set `events.hs_offset_ms / to_offset_ms`.
* **velocity**: foot AP velocity crossing −frac·v (needs belt speed).
Planned: train/tune against the instrumented treadmill (force threshold events).

## 7. Belt speed and spatial parameters
During flat-foot stance the foot moves with the belt → v = −median(foot AP velocity). Three
estimates are reported: 2D-only (foot pixels back-projected to horizontal planes at their stance
heights — projecting to Y = 0 would inflate the speed by C_y/(C_y − h)), refined (optimisation
variable), and from the final 3D/model markers.

Spatial parameters in belt coordinates u = x + v·t (constant for a planted foot):
stride length = v·ΔT + Δx_HS, step length = v·(t_ipsi − t_contra) + (x_ipsi − x_contra),
i.e. the equivalent over-ground distances, corrected for the subject drifting on the belt.
Step width = |ΔZ| of the heels at consecutive heel strikes.
