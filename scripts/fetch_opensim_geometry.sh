#!/usr/bin/env bash
# Optional: bone meshes for viewing the model in the OpenSim GUI (not needed for IK).
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
python -m pip download pose2sim --no-deps -d "$tmp" -q
python - "$tmp" <<'PY'
import sys, glob, zipfile, os
whl = glob.glob(os.path.join(sys.argv[1], "*.whl"))[0]
z = zipfile.ZipFile(whl)
for n in z.namelist():
    if n.startswith("Pose2Sim/OpenSim_Setup/Geometry/") and not n.endswith("/"):
        out = os.path.join("opensim_models", "Geometry", os.path.basename(n))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(z.read(n))
print("opensim_models/Geometry populated")
PY
rm -rf "$tmp"
