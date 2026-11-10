import { api } from "../api.js";
import { h, clear, icon, fmt, modal, field, select, numInput, card, emptyState, rmsBadge, jobBadge, progressBar, toast, store } from "../ui.js";

export async function render(view, _params, ctx) {
  const root = h("div");
  view.append(root);
  let o;
  const load = async () => { o = await api.get("/api/overview"); draw(); };

  function draw() {
    const users = (id) => o.subjects.filter((s) => s.meta.intrinsics === id).map((s) => s.id);
    const newBtn = h("button", { class: "btn primary", onclick: () => newCameraDialog(o.subjects, ctx) }, icon("plus", 16), "New from checkerboard");
    clear(root).append(h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Cameras"), h("div", { class: "sub" }, "Lens intrinsics (focal length + distortion) from a checkerboard video. Once per camera, resolution, orientation and zoom.")),
      h("div", { class: "actions" }, newBtn)));

    const running = ctx.jobs.filter((j) => j.kind === "intrinsics" && ["queued", "running"].includes(j.status));
    for (const j of running) {
      root.append(h("div", { class: "banner run", style: { marginBottom: "14px" } }, icon("loader", 16, "spin"),
        h("div", { class: "grow" }, h("div", { class: "row" }, h("b", {}, j.title), jobBadge(j, false)),
          h("span", { class: "small ink2" }, `Detecting the board in ${j.meta.video}. This can take a few minutes for long videos.`), progressBar({ ...j, progress: null })),
        h("a", { class: "btn sm", href: `#/jobs/${j.id}` }, "Log")));
    }

    if (!o.intrinsics.length) {
      root.append(h("div", { class: "card" }, emptyState("camera", "No camera calibrated yet",
        "Film a printed checkerboard from many angles with the same camera settings as the trials, add the video to a subject, then compute the intrinsics here.",
        h("button", { class: "btn primary", onclick: () => newCameraDialog(o.subjects, ctx) }, icon("plus", 16), "New from checkerboard"))));
    } else {
      root.append(h("div", { class: "cards" }, o.intrinsics.map((c) => {
        const [w, hh] = c.image_size || [];
        const u = users(c.id);
        return h("div", { class: "card card-pad", style: { display: "grid", gap: "12px" } },
          h("div", { class: "row" }, h("div", {}, h("div", { style: { fontWeight: 700, fontSize: "16px" } }, c.name), h("div", { class: "small muted mono" }, c.id)),
            h("span", { class: "spacer" }), rmsBadge(c.rms_px, 0.5, 1.0)),
          h("dl", { class: "kv" },
            h("dt", {}, "Image"), h("dd", {}, w ? `${w} × ${hh} (${w > hh ? "landscape" : "portrait"})` : "–"),
            h("dt", {}, "Focal length"), h("dd", {}, `${fmt.n(c.fx, 0)} / ${fmt.n(c.fy, 0)} px`),
            h("dt", {}, "Principal point"), h("dd", {}, `${fmt.n(c.cx, 0)}, ${fmt.n(c.cy, 0)} px`),
            h("dt", {}, "Distortion"), h("dd", { class: "small" }, (c.dist || []).map((v) => fmt.n(v, 3)).join("  ")),
            h("dt", {}, "Updated"), h("dd", {}, fmt.ago(c.updated)),
            h("dt", {}, "Used by"), h("dd", {}, u.length ? u.map((id, i) => [i ? ", " : "", h("a", { href: `#/s/${encodeURIComponent(id)}` }, id)]) : h("span", { class: "muted" }, "no subjects"))));
      })));
    }

    root.append(h("div", { class: "section-title" }, h("h2", {}, "Recording a good checkerboard video")),
      card(null, null, null, h("div", { class: "card-body" }, h("ul", { style: { margin: 0, paddingLeft: "18px", display: "grid", gap: "6px" }, class: "ink2" },
        h("li", {}, "Same camera, resolution, orientation (portrait/landscape), zoom and focus as the trials. Change any of these and you need a new calibration."),
        h("li", {}, "Print the board flat and rigid; measure one square with a ruler (printers scale)."),
        h("li", {}, "Move and tilt the board (±30–45°) through the whole frame, including the corners, slowly enough to avoid blur."),
        h("li", {}, "RMS below 0.5 px is good; above 1 px usually means blur, the wrong board size, or too few distinct views.")))));
  }

  let sig = "";
  ctx.onJobs((jobs) => {
    const n = jobs.filter((j) => j.kind === "intrinsics").map((j) => `${j.id}:${j.status}`).join("|");
    if (sig && n !== sig) load();
    sig = n;
  });
  await load();
  const pre = store("camera-prefill");
  if (pre) { store("camera-prefill", null); newCameraDialog(o.subjects, ctx, pre); }
}

async function newCameraDialog(subjects, ctx, pre = {}) {
  if (!subjects.length) { toast("Create a subject first", "Add the checkerboard video to a subject, then come back.", "warn"); return; }
  const last = store("board") || { cols: 7, rows: 4, square_mm: 40, step: 20 };
  const subjSel = select(subjects.map((s) => [s.id, s.id]), pre.subject || subjects[0].id);
  const videoSel = select([], null);
  const fillVideos = async () => {
    const s = await api.get(`/api/subjects/${api.enc(subjSel.value)}`);
    clear(videoSel);
    const vids = [...s.videos].sort((a, b) => (b.role === "checkerboard") - (a.role === "checkerboard"));
    vids.forEach((v) => videoSel.append(h("option", { value: v.name }, `${v.name}${v.role === "checkerboard" ? "  (checkerboard)" : ""}`)));
    if (pre.video && vids.some((v) => v.name === pre.video)) videoSel.value = pre.video;
    if (!vids.length) videoSel.append(h("option", { value: "" }, "No videos in this subject"));
  };
  subjSel.onchange = fillVideos;
  await fillVideos();
  const name = h("input", { type: "text", value: pre.name || "", placeholder: "e.g. iphone_portrait_1080p" });
  const cols = numInput(last.cols, null, { min: 2, step: 1 });
  const rows = numInput(last.rows, null, { min: 2, step: 1 });
  const sq = numInput(last.square_mm, "mm", { min: 1, step: 0.1 });
  const step = numInput(last.step, "frames", { min: 1, step: 1 });
  modal({
    title: "New camera calibration",
    sub: "Detects the checkerboard in the video and solves focal length + lens distortion (OpenCV).",
    okLabel: "Start",
    body: h("div", { class: "form-grid" },
      h("div", { class: "full" }, field("Camera name", name, "Saved as data/intrinsics/<name>.json")),
      field("Subject", subjSel), field("Checkerboard video", videoSel),
      field("Inner corners across", cols.el, "Count corners where 4 squares meet, not squares: 8 squares → 7"),
      field("Inner corners down", rows.el, "5 squares → 4"),
      field("Square size", sq.el, "Edge of one square, measured on the print"),
      field("Use every Nth frame", step.el, "Larger is faster; at least 8 frames must show the whole board")),
    onOk: async () => {
      if (!videoSel.value) throw new Error("Pick a video");
      const b = { cols: +cols.input.value, rows: +rows.input.value, square_mm: +sq.input.value, step: +step.input.value };
      store("board", b);
      const j = await api.post("/api/intrinsics", { name: name.value.trim(), subject: subjSel.value, video: videoSel.value,
        cols: b.cols, rows: b.rows, square_m: b.square_mm / 1000, step: b.step });
      toast("Camera calibration started", "When it finishes, pick it for the subject (Edit details).", "info", { href: `#/jobs/${j.id}`, label: "Open log" });
      ctx.pollNow();
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    },
  });
}
