import { app } from "../../scripts/app.js";

const BOX = 46; // px of the longest possible side (2160) inside a tile
const CUSTOM = "Custom";

function gcd(a, b) { return b ? gcd(b, a % b) : a; }
function ratioText(w, h) {
  const g = gcd(w, h);
  const rw = w / g, rh = h / g;
  if (rw <= 32 && rh <= 32) return `${rw}:${rh}`;
  return w >= h ? `${(w / h).toFixed(2)}:1` : `1:${(h / w).toFixed(2)}`;
}

const STYLE = `
.spp-root { display:flex; flex-direction:column; gap:6px; padding:4px 2px; box-sizing:border-box;
  font-family:sans-serif; color:var(--input-text, #ddd); overflow:auto; height:100%; }
.spp-head { font-size:10px; letter-spacing:.08em; opacity:.6; text-transform:uppercase; margin-top:2px; }
.spp-grid { display:flex; flex-wrap:wrap; gap:4px; }
.spp-tile { width:66px; display:flex; flex-direction:column; align-items:center; gap:2px; padding:4px 2px;
  border:1px solid var(--border-color, #444); border-radius:6px; cursor:pointer;
  background:var(--comfy-input-bg, #222); user-select:none; }
.spp-tile:hover { border-color:#8ab4f8; }
.spp-tile.sel { border-color:#4caf50; background:rgba(76,175,80,.18); }
.spp-tile.custom { border-style:dashed; }
.spp-frame { width:${BOX}px; height:${BOX}px; display:flex; align-items:center; justify-content:center; }
.spp-rect { background:rgba(138,180,248,.35); border:1px solid #8ab4f8; border-radius:2px; }
.spp-tile.sel .spp-rect { background:rgba(76,175,80,.55); border-color:#4caf50; }
.spp-dim { font-size:10px; line-height:1.1; white-space:nowrap; }
.spp-sub { font-size:9px; opacity:.6; line-height:1.1; white-space:nowrap; }
.spp-hint { font-size:10px; opacity:.6; align-self:center; max-width:360px; }
`;

app.registerExtension({
  name: "SizePresetPicker",
  setup() {
    const s = document.createElement("style");
    s.textContent = STYLE;
    document.head.appendChild(s);
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "SizePresetPicker") return;
    const meta = nodeData.input?.required?.preset?.[1]?.presets_meta ?? [];
    const maxSide = Math.max(...meta.map((p) => Math.max(p.w, p.h)));

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const node = this;
      const combo = node.widgets.find((w) => w.name === "preset");
      const cw = node.widgets.find((w) => w.name === "custom_width");
      const ch = node.widgets.find((w) => w.name === "custom_height");

      // Picking a preset copies its size into the custom fields, so they always show the real output.
      function select(label, w, h) {
        combo.value = label;
        combo.callback?.(label);
        if (w && h) {
          cw.value = w;
          ch.value = h;
        }
        refresh();
        node.setDirtyCanvas(true, true);
      }

      function makeTile(w, h, dimText, subText, onPick) {
        const tile = document.createElement("div");
        tile.className = "spp-tile";
        const frame = document.createElement("div");
        frame.className = "spp-frame";
        const rect = document.createElement("div");
        rect.className = "spp-rect";
        frame.appendChild(rect);
        const dim = document.createElement("div");
        dim.className = "spp-dim";
        const sub = document.createElement("div");
        sub.className = "spp-sub";
        tile.append(frame, dim, sub);
        tile.addEventListener("pointerdown", (e) => {
          e.stopPropagation();
          onPick();
        });
        tile.update = (w, h, dimText, subText) => {
          // Scaled against the largest preset, so tiles show relative size as well as shape.
          const s = BOX / Math.max(maxSide, w, h);
          rect.style.width = `${Math.max(4, w * s)}px`;
          rect.style.height = `${Math.max(4, h * s)}px`;
          dim.textContent = dimText;
          sub.textContent = subText;
          sub.style.display = subText ? "" : "none";
          tile.title = `${w} x ${h}  (${ratioText(w, h)}, ${((w * h) / 1e6).toFixed(2)} MP)`;
        };
        tile.update(w, h, dimText, subText);
        return tile;
      }

      const root = document.createElement("div");
      root.className = "spp-root";
      const tiles = new Map();
      const groups = [
        ["Portrait", meta.filter((p) => p.h > p.w)],
        ["Square", meta.filter((p) => p.h === p.w)],
        ["Landscape", meta.filter((p) => p.w > p.h)],
      ];
      for (const [title, items] of groups) {
        if (!items.length) continue;
        const head = document.createElement("div");
        head.className = "spp-head";
        head.textContent = title;
        const grid = document.createElement("div");
        grid.className = "spp-grid";
        for (const p of items) {
          const tile = makeTile(p.w, p.h, `${p.w}×${p.h}`, "", () => select(p.label, p.w, p.h));
          tiles.set(p.label, tile);
          grid.appendChild(tile);
        }
        root.append(head, grid);
      }

      const head = document.createElement("div");
      head.className = "spp-head";
      head.textContent = "Custom";
      const grid = document.createElement("div");
      grid.className = "spp-grid";
      const customTile = makeTile(cw.value, ch.value, "", "", () => select(CUSTOM));
      customTile.classList.add("custom");
      tiles.set(CUSTOM, customTile);
      const hint = document.createElement("div");
      hint.className = "spp-hint";
      hint.textContent = "Edit custom_width / custom_height above to use your own size. Editing them switches to Custom.";
      grid.append(customTile, hint);
      root.append(head, grid);

      let shown = null;
      let customKey = null;
      function refresh() {
        const key = `${cw.value}x${ch.value}`;
        if (customKey !== key) {
          customTile.update(cw.value, ch.value, `${cw.value}×${ch.value}`, "");
          customKey = key;
        }
        if (shown === combo.value) return;
        tiles.get(shown)?.classList.remove("sel");
        tiles.get(combo.value)?.classList.add("sel");
        shown = combo.value;
      }

      node.addDOMWidget("preset_grid", "preset_grid", root, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 300,
      });

      // Keep the highlight in sync when the dropdown is changed or a workflow is loaded.
      const comboCb = combo.callback;
      combo.callback = function () {
        const res = comboCb?.apply(this, arguments);
        refresh();
        return res;
      };
      // Typing a size by hand means the user wants Custom.
      for (const w of [cw, ch]) {
        const cb = w.callback;
        w.callback = function () {
          const res = cb?.apply(this, arguments);
          if (combo.value !== CUSTOM) {
            combo.value = CUSTOM;
            comboCb?.call(combo, CUSTOM);
          }
          refresh();
          return res;
        };
      }
      const onConfigure = node.onConfigure;
      node.onConfigure = function () {
        const res = onConfigure?.apply(this, arguments);
        refresh();
        return res;
      };
      const onDrawForeground = node.onDrawForeground;
      node.onDrawForeground = function () {
        refresh();
        return onDrawForeground?.apply(this, arguments);
      };
      refresh();
      if (node.size[0] < 560) node.setSize([560, Math.max(node.size[1], 760)]);
      return r;
    };
  },
});
