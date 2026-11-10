"""Web app: a browser UI over the Humotech Gait Analysis workflow (`humotech app`).

Everything lives in one data folder (default ``data/``)::

    data/
      intrinsics.json, intrinsics/<name>.json     camera intrinsics (checkerboard)
      <subject>/
        subject.json                              height, mass, notes, chosen intrinsics
        *.mov | *.mp4 ...                         trial videos (+ checkerboard videos)
        calibration.json, calibration.png         belt calibration (clicked in the app or CLI)
        results/<trial>/                          pipeline outputs per trial video
      .jobs/                                      job records + logs of background runs
"""
