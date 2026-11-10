import { api } from "../api.js";
import { h, clear, icon, fmt, card, toast } from "../ui.js";

const ROLE = {
  numpy: "core", scipy: "core", cv2: "video + calibration", pandas: "core", yaml: "config",
  torch: "3D refinement (GPU if CUDA)", opensim: "scaling + inverse kinematics", rtmlib: "2D pose (RTMPose)",
  onnxruntime: "2D pose runtime", ultralytics: "YOLO pose (optional)", smplx: "GVHMR / WHAM (optional)",
};
const REQUIRED = new Set(["numpy", "scipy", "cv2", "pandas", "yaml", "torch", "rtmlib", "onnxruntime"]);

export async function render(view, _p, ctx) {
  const body = h("div", { class: "stack" });
  const refresh = h("button", { class: "btn", onclick: () => load(true) }, icon("refresh", 15), "Re-check");
  const selftest = h("button", { class: "btn", onclick: async () => {
    const j = await api.post("/api/selftest");
    ctx.pollNow();
    toast("Self-test started", "Runs the full pipeline on a synthetic walker with known answers.", "info", { href: `#/jobs/${j.id}`, label: "Open log" });
  } }, icon("zap", 15), "Run self-test");
  view.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "System"),
    h("div", { class: "sub" }, "What this machine can run. Jobs use the same Python environment as the app.")),
  h("div", { class: "actions" }, selftest, refresh)), body);

  async function load(force = false) {
    clear(body).append(h("div", { class: "muted row" }, icon("loader", 16, "spin"), "Checking installed packages…"));
    refresh.disabled = true;
    try {
      const s = await api.get(`/api/system${force ? "?refresh=1" : ""}`);
      draw(s);
    } finally { refresh.disabled = false; }
  }

  function draw(s) {
    clear(body);
    const byName = Object.fromEntries(s.packages.map((p) => [p.name, p]));
    const torch = byName.torch, ort = byName.onnxruntime;
    const torchCuda = torch?.ok && /cuda=True/.test(torch.detail);
    const ortCuda = ort?.ok && /CUDAExecutionProvider/.test(ort.detail);
    const gpuOk = torchCuda && ortCuda;
    const missingReq = s.packages.filter((p) => REQUIRED.has(p.name) && !p.ok);
    const opensimOk = byName.opensim?.ok;

    const items = [];
    if (missingReq.length) items.push(["bad", "alert", `Missing: ${missingReq.map((p) => p.name).join(", ")}`, "Run scripts/setup_ubuntu.sh (or setup_mac.sh) in this environment."]);
    if (!opensimOk) items.push(["warn", "alert", "OpenSim not available", "Joint angles are skipped; untick “OpenSim” when processing. Install with conda: conda install -c opensim-org opensim."]);
    if (s.gpus.length && !gpuOk) items.push(["warn", "alert", "GPU present but not fully usable",
      `${torchCuda ? "" : "PyTorch has no CUDA. "}${ortCuda ? "" : "onnxruntime lacks the CUDA provider. "}Process with CPU or fix the install (README → Troubleshooting).`]);
    if (gpuOk) items.push(["good", "check", "GPU ready", "Pose detection and refinement can run on CUDA."]);
    if (!s.gpus.length) items.push(["", "info", "No NVIDIA GPU detected", "Everything runs on CPU (slower 2D pose)."]);
    body.append(...items.map(([cls, ic, title, text]) => h("div", { class: `banner ${cls}` }, icon(ic, 16), h("div", { class: "grow" }, h("b", {}, title), h("span", { class: "small" }, text)))));

    if (s.gpus.length) {
      body.append(h("div", { class: "grid-2" }, s.gpus.map((g) => card(g.name, `driver ${g.driver}`, null, h("div", { class: "card-body", style: { display: "grid", gap: "10px" } },
        h("div", { class: "row small" }, h("span", { class: "ink2" }, "Memory"), h("span", { class: "spacer" }),
          h("span", { class: "tabnum" }, `${fmt.n(g.mem_used_mb / 1024, 1)} / ${fmt.n(g.mem_total_mb / 1024, 1)} GB`)),
        h("div", { class: "progress" }, h("div", { style: { width: `${(100 * g.mem_used_mb) / g.mem_total_mb}%` } })),
        h("div", { class: "row small" }, h("span", { class: "ink2" }, "Utilisation"), h("span", { class: "spacer" }), h("span", { class: "tabnum" }, `${fmt.n(g.util_pct, 0)} %`)))))));
    }

    body.append(card("Python packages", s.python, null, h("div", { class: "table-wrap" }, h("table", { class: "t" },
      h("thead", {}, h("tr", {}, h("th", {}, "Package"), h("th", {}, "Used for"), h("th", {}, "Status"), h("th", {}, "Details"))),
      h("tbody", {}, s.packages.map((p) => h("tr", {},
        h("td", { class: "mono" }, p.name), h("td", { class: "ink2" }, ROLE[p.name] || ""),
        h("td", {}, p.ok ? h("span", { class: "badge good" }, icon("check", 12), "OK")
          : h("span", { class: `badge ${REQUIRED.has(p.name) ? "bad" : ""}` }, icon(REQUIRED.has(p.name) ? "alert" : "x", 12), "Missing")),
        h("td", { class: "small mono ink2", style: { wordBreak: "break-word" } }, p.detail))))))),
    card("Paths", null, null, h("div", { class: "card-body" }, h("dl", { class: "kv" },
      h("dt", {}, "Data folder"), h("dd", { class: "mono small" }, s.data_root),
      h("dt", {}, "Python"), h("dd", { class: "mono small" }, s.executable),
      h("dt", {}, "Checked"), h("dd", {}, fmt.ago(s.checked))))));
  }
  await load();
}
