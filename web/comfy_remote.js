import { app } from "../../scripts/app.js";

// Workflow groups that become tabs on the phone page.
const SECTIONS = {
  t2i: { group: "TEXT TO IMAGE TURBO", label: "Text to Image" },
  depth: { group: "DEPTH CONTROL TURBO", label: "Depth" },
};

function inGroup(group, node) {
  const b = group._bounding || group.bounding;
  const [x, y] = node.pos;
  return x >= b[0] && y >= b[1] && x < b[0] + b[2] && y < b[1] + b[3];
}

// A group titled "MODELS…" holds loaders both sections use, so capturing a section never switches it off.
const isShared = (group) => /^MODELS\b/i.test(group.title);

const outputNodeCache = {};
async function isOutputNode(classType) {
  if (!(classType in outputNodeCache)) {
    const r = await fetch(`/object_info/${encodeURIComponent(classType)}`);
    const info = r.ok ? (await r.json())[classType] : null;
    outputNodeCache[classType] = !!info?.output_node;
  }
  return outputNodeCache[classType];
}

// Turn one group on (and every other group off) just long enough to build its API prompt,
// then put every node's mode back.
async function captureSection(groupTitle) {
  const graph = app.rootGraph ?? app.graph;
  const group = graph.groups.find((g) => g.title === groupTitle);
  if (!group) throw new Error(`Group "${groupTitle}" not found in the open workflow`);

  const saved = [];
  const setMode = (n, m) => { saved.push([n, n.mode]); n.mode = m; };
  const walk = (sub, from, to) => {
    for (const n of sub._nodes ?? sub.nodes ?? []) {
      if (n.mode === from) setMode(n, to);
      if (n.subgraph) walk(n.subgraph, from, to);
    }
  };
  const members = new Set();
  for (const n of graph._nodes) {
    if (inGroup(group, n)) {
      members.add(String(n.id));
      if (n.mode === 4) setMode(n, 0);
      if (n.subgraph) walk(n.subgraph, 4, 0);
    } else if (graph.groups.some((g) => g !== group && !isShared(g) && inGroup(g, n))) {
      if (n.mode === 0) setMode(n, 4);
      if (n.subgraph) walk(n.subgraph, 0, 4);
    }
  }
  let result;
  try {
    result = await app.graphToPrompt();
  } finally {
    for (const [n, m] of saved.reverse()) n.mode = m;
    graph.setDirtyCanvas?.(true, true);
  }

  // Keep only what this section's output nodes actually need (drops pickers etc. from other sections).
  const prompt = result.output;
  const keep = new Set();
  const stack = [];
  for (const [id, node] of Object.entries(prompt)) {
    if (members.has(id.split(":")[0]) && (await isOutputNode(node.class_type))) stack.push(id);
  }
  while (stack.length) {
    const id = stack.pop();
    if (keep.has(id) || !prompt[id]) continue;
    keep.add(id);
    for (const v of Object.values(prompt[id].inputs)) {
      if (Array.isArray(v) && v.length === 2 && typeof v[0] === "string" && prompt[v[0]]) stack.push(v[0]);
    }
  }
  const pruned = Object.fromEntries(Object.entries(prompt).filter(([id]) => keep.has(id)));
  return { prompt: pruned, workflow: result.workflow };
}

async function sendToPhone() {
  const out = {};
  try {
    for (const [key, s] of Object.entries(SECTIONS)) {
      const cap = await captureSection(s.group);
      out[key] = { label: s.label, group: s.group, captured: Date.now(),
        workflowName: app.workflowManager?.activeWorkflow?.filename ?? document.title, ...cap };
    }
    const r = await fetch("/mobile/templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(out) });
    if (!r.ok) throw new Error(await r.text());
    app.extensionManager?.toast?.add({ severity: "success", summary: "Comfy Remote",
      detail: `Sent ${Object.values(SECTIONS).map((s) => s.group).join(" + ")} to Comfy Remote. Open /remote on your phone or PC.`, life: 5000 });
    return out;
  } catch (e) {
    app.extensionManager?.toast?.add({ severity: "error", summary: "Comfy Remote", detail: String(e.message || e), life: 8000 });
    throw e;
  }
}

window.ComfyRemote = window.MobileRemote = { sendToPhone, captureSection };

app.registerExtension({
  name: "ComfyRemote",
  commands: [{ id: "ComfyRemote.send", label: "Send sections to Comfy Remote", icon: "pi pi-mobile", function: sendToPhone }],
  menuCommands: [{ path: ["Extensions", "Comfy Remote"], commands: ["ComfyRemote.send"] }],
});
