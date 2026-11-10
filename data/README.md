Session data. Videos (*.mp4, *.mov, *.avi) and *.npz are git-ignored; JSON/CSV/plots are tracked.

    data/
      intrinsics.json        # from `humotech intrinsics` (shared by all sessions with this camera/zoom)
      S01/
        intrinsic.mov        # checkerboard video (git-ignored)
        trial.mp4            # treadmill video (git-ignored)
        calibration.json     # from `humotech calibrate`
        results/             # from `humotech run`
      synthetic/             # from `humotech synth --run` (reference run with ground truth)

`intrinsics.json` was made with:

    humotech intrinsics data/S01/intrinsic.mov --board 7x4 --square 0.04 --step 20 --out data/intrinsics.json
