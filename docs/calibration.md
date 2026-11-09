# Recording & calibration protocol

## Treadmill coordinate frame (= OpenSim ground frame)

* origin: centre of the belt surface
* **+X** forward — toward the front of the treadmill, the direction the subject faces
* **+Y** up — the belt surface is the plane Y = 0
* **+Z** to the subject's right

Everything (3D keypoints, OpenSim model, foot positions) is expressed in this frame.

## Camera placement

* Static tripod, **side-on** (roughly perpendicular to the walking direction), whole body and the
  whole visible belt in frame for the entire trial, with some margin above the head.
* **Mount the camera higher than hip height and tilt it down** (e.g. 1.3–1.8 m high, 3–4 m away).
  Monocular depth is recovered mostly from "the stance foot lies on the belt plane"; the more the
  camera looks down on the belt, the better that constrains depth (a 1 cm foot-height error moves
  the foot ~1 / tan(tilt) cm in depth: ×2.8 at 20° tilt, ×1.7 at 30°).
* ≥ 60 fps (100–120 fps preferred), short shutter (≤ 1/500 s) to avoid motion blur of the feet,
  good even lighting, contrasting clothing/shoes vs. belt.
* Lock focus, zoom and exposure; **disable digital/optical stabilisation** and any "lens
  correction" that changes per frame. If you change zoom, redo the intrinsics.
* Avoid wide-angle extremes; if unavoidable, the checkerboard intrinsics (with distortion) are a must.

## What to measure (tape measure, metres)

| Required | Why |
|---|---|
| Belt length & width of the 4 corners you will click | metric scale + belt plane → homography / camera pose |
| Subject height, mass | model scaling (mass), anthropometric priors |

| Recommended | Why |
|---|---|
| Checkerboard video → `humotech intrinsics` | focal length + lens distortion; 4 coplanar points only weakly determine focal length |
| ≥ 1 landmark **off** the belt plane with known (X, Y, Z) — e.g. both handrail tops, or a 1 m pole stood on a belt corner | pins down focal length / camera tilt, independent check |
| Extra points on the belt plane (tape marks at known X/Z) | redundancy, error estimate |
| Treadmill's displayed speed | validation of the foot-speed belt estimate |
| Force-plate data (synchronised) | ground-truth gait events — tune `events.*_offset_ms` per method |
| 3–5 s quiet standing at trial start | cleaner scaling |

Sync tip: start each trial with a single firm stomp (visible in video + sharp force-plate peak).

Belt "corners": use the four corners of the **visible belt surface** you can identify precisely
(e.g. where the belt meets the side rails at the front roller and rear roller, or put tape marks
on the deck rails at a measured spacing and use those). What matters is that the four points lie
on the belt plane and form a rectangle of the length/width you enter.

## Clicking (`humotech calibrate`)

```bash
humotech calibrate trial.mp4 --belt-length 1.60 --belt-width 0.50 \
    --intrinsics intrinsics.json --extra extra_landmarks.yaml --out calibration.json
```

Click order is shown on screen: `belt_front_left, belt_front_right, belt_back_right, belt_back_left`
(left/right are the **subject's** left/right). A magnifier follows the cursor; `u` undoes, `s`
skips an optional extra landmark, Enter accepts. `extra_landmarks.yaml` example:

```yaml
rail_front_left_top:  [0.80, 1.02, -0.40]   # X forward, Y up, Z right (m)
rail_front_right_top: [0.80, 1.02,  0.40]
```

A preview PNG is written next to the JSON: a 10 cm grid must lie on the belt and the green
posts are 1 m tall — check them against the subject or the handrails. `calibration.json` reports
per-landmark reprojection errors; > 2–3 px usually means a mis-click or wrong dimensions.
