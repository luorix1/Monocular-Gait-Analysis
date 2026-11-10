Session data, used by both the CLI and the web app (`humotech app --data data`).
Videos (*.mp4, *.mov, *.avi) and *.npz are git-ignored; JSON/CSV/plots are tracked.

    data/
      intrinsics.json          # default camera, from `humotech intrinsics`
      intrinsics/<name>.json   # further cameras made in the app (Cameras page)
      S01/
        subject.json           # height, mass, notes, chosen intrinsics, video roles (written by the app)
        intrinsic.mov          # checkerboard video (git-ignored)
        0p8mps_walk.mov ...    # trial videos (git-ignored); "1p2mps" in a name pre-fills 1.2 m/s
        calibration.json       # belt calibration, from the app or `humotech calibrate`
        calibration.png        # preview: belt grid + 1 m posts projected on the frame
        results/<trial>/       # pipeline outputs per video, from the app or `humotech run`
      synthetic/               # from `humotech synth --run` (reference run with ground truth)
      .jobs/                   # web-app job records and logs (git-ignored)

`intrinsics.json` was made with:

    humotech intrinsics data/S01/intrinsic.mov --board 7x4 --square 0.04 --step 20 --out data/intrinsics.json
