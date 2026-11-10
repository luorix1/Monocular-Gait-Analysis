import { api } from "../api.js";
import { h, icon, fmt, modal, field, numInput, select, emptyState, rmsBadge } from "../ui.js";

export async function render(view) {
  const o = await api.get("/api/overview");
  const newBtn = h("button", { class: "btn primary", onclick: () => newSubjectDialog(o.intrinsics) }, icon("plus", 16), "New subject");
  view.append(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "Subjects"), h("div", { class: "sub" }, "Each subject has its own videos, belt calibration and results.")),
    h("div", { class: "actions" }, newBtn)));

  view.append(workflowStrip(o));

  if (!o.subjects.length) {
    view.append(h("div", { class: "card" }, emptyState("users", "No subjects yet",
      "Create a subject, add their treadmill videos, click the belt corners once, then process the trials.", newBtn.cloneNode(true))));
    view.querySelector(".empty .btn").onclick = () => newSubjectDialog(o.intrinsics);
    return;
  }
  const grid = h("div", { class: "cards" });
  for (const s of o.subjects) {
    const m = s.meta;
    const done = s.n_trials && s.n_processed === s.n_trials;
    grid.append(h("a", { class: "card subject-card", href: `#/s/${encodeURIComponent(s.id)}` },
      h("div", { class: "row" }, h("div", { class: "id" }, s.id), h("span", { class: "spacer" }),
        s.calibrated ? rmsBadge(s.calibration_rms_px) : h("span", { class: "badge warn" }, icon("alert", 12), "Not calibrated")),
      h("dl", { class: "kv" },
        h("dt", {}, "Height"), h("dd", {}, m.height_m ? `${fmt.n(m.height_m, 2)} m` : "–"),
        h("dt", {}, "Mass"), h("dd", {}, m.mass_kg ? `${fmt.n(m.mass_kg, 1)} kg` : "–"),
        h("dt", {}, "Camera"), h("dd", {}, m.intrinsics ? (m.intrinsics === "intrinsics.json" ? "default" : m.intrinsics.replace(/^intrinsics\//, "").replace(/\.json$/, "")) : "none")),
      h("div", { class: "mini-progress" },
        h("div", { class: "row small" }, h("span", { class: "ink2" }, `${s.n_processed} of ${s.n_trials} trials processed`),
          h("span", { class: "spacer" }), done ? h("span", { class: "badge good" }, icon("check", 12), "Complete") : null),
        h("div", { class: "progress" }, h("div", { style: { width: `${s.n_trials ? (100 * s.n_processed) / s.n_trials : 0}%`, background: "var(--good)" } }))),
      m.notes ? h("div", { class: "small muted" }, m.notes) : null));
  }
  view.append(grid);
}

function workflowStrip(o) {
  const hasCam = o.intrinsics.length > 0;
  const steps = [
    ["camera", "Camera", hasCam ? `${o.intrinsics.length} calibrated` : "Calibrate the lens once", "#/cameras", hasCam],
    ["users", "Subject", "Height, mass and videos", null, o.subjects.length > 0],
    ["target", "Belt", "Click the 4 belt corners", null, o.subjects.some((s) => s.calibrated)],
    ["activity", "Process", "Pose → 3D → OpenSim → gait", null, o.subjects.some((s) => s.n_processed > 0)],
  ];
  return h("div", { class: "card card-pad", style: { marginBottom: "22px" } },
    h("div", { class: "row", style: { gap: "8px 18px" } },
      h("span", { class: "small muted", style: { fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" } }, "Workflow"),
      steps.map(([ic, title, sub, href, ok], i) => [
        i ? h("span", { class: "muted" }, icon("chevron", 14)) : null,
        h(href ? "a" : "span", { href, class: "row", style: { gap: "8px", color: "inherit", textDecoration: "none" } },
          h("span", { style: { color: ok ? "var(--good)" : "var(--muted)" } }, icon(ok ? "check" : ic, 16)),
          h("span", {}, h("b", {}, title), h("span", { class: "muted small" }, ` · ${sub}`))),
      ])));
}

export function newSubjectDialog(intrinsics, existing) {
  const id = h("input", { type: "text", placeholder: "e.g. S02", value: existing?.id || "", disabled: !!existing });
  const height = numInput(existing?.meta.height_m, "m", { min: 0.5, max: 2.5, placeholder: "1.75" });
  const mass = numInput(existing?.meta.mass_kg, "kg", { min: 10, max: 250, placeholder: "70" });
  const intr = select([["", "None (estimate focal length from the belt)"], ...intrinsics.map((i) => [i.id, `${i.name} · ${i.image_size?.join("×")} · RMS ${fmt.n(i.rms_px, 2)} px`])],
    existing ? existing.meta.intrinsics || "" : intrinsics[0]?.id || "");
  const notes = h("textarea", { rows: 2, placeholder: "Optional", style: { fontFamily: "var(--font)", fontSize: "14px" } }, existing?.meta.notes || "");
  modal({
    title: existing ? `Edit ${existing.id}` : "New subject",
    sub: "Height and mass scale the OpenSim model. Videos are added on the next page.",
    okLabel: existing ? "Save" : "Create subject",
    body: h("div", { class: "form-grid" },
      h("div", { class: "full" }, field("Subject ID", id, "Also the folder name inside the data folder.")),
      field("Height", height.el), field("Body mass", mass.el),
      h("div", { class: "full" }, field("Camera intrinsics", intr, "The checkerboard calibration of the camera that filmed this subject.")),
      h("div", { class: "full" }, field("Notes", notes))),
    onOk: async () => {
      const body = { height_m: height.input.value, mass_kg: mass.input.value, intrinsics: intr.value || null, notes: notes.value };
      if (existing) {
        await api.patch(`/api/subjects/${api.enc(existing.id)}`, body);
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      } else {
        const s = await api.post("/api/subjects", { id: id.value.trim(), ...body });
        location.hash = `#/s/${encodeURIComponent(s.id)}`;
      }
    },
  });
}
