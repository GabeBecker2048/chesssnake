// The Account page's "Board marks" card: the colours of highlights, arrows and
// rings, and of the Ctrl, Alt and Ctrl+Alt overrides. Each can be one of the
// named presets or any rrggbb typed in; a small board beside them previews the
// result as you choose, and each change is saved to the server (as "#rrggbb")
// a moment after you stop changing it.

import { Board } from "../board.js";
import { PRESETS, safeColor } from "../draw.js";
import { DEFAULTS, setting, updateSettings } from "../settings.js";
import { h, showError } from "../ui.js";

const ROWS = [
  ["mark_highlight_color", "Highlight", "right-click"],
  ["mark_arrow_color", "Arrow and ring", "right-drag, middle-click"],
  ["mark_ctrl_color", "Ctrl", "hold while marking"],
  ["mark_alt_color", "Alt", "hold while marking"],
  ["mark_ctrl_alt_color", "Ctrl + Alt", "hold while marking"],
];

// A position with something on most squares the marks cross (the Italian Game).
const PREVIEW_FEN = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4";

const SAVE_DELAY_MS = 500;

/** "7B3FC4", "#7b3fc4" -> "#7b3fc4"; anything else -> null. */
function parseHex(text) {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(text.trim());
  return m ? `#${m[1].toLowerCase()}` : null;
}

export function markColoursCard() {
  const palette = {};
  for (const [name] of ROWS) palette[name] = safeColor(setting(name), DEFAULTS[name]);

  const preview = new Board({ orientation: "white", mini: true, marks: true });
  preview.setPosition(PREVIEW_FEN);
  const status = h("span", { class: "muted small", role: "status" });
  const rows = new Map(); // name -> {sync()}
  const timers = new Map();

  function drawPreview() {
    preview.setShapes([
      { kind: "square", from: "c5", color: palette.mark_highlight_color },
      { kind: "square", from: "f7", color: palette.mark_highlight_color },
      { kind: "arrow", from: "c4", to: "f7", color: palette.mark_arrow_color },
      { kind: "circle", from: "e5", color: palette.mark_arrow_color },
      { kind: "arrow", from: "f3", to: "g5", color: palette.mark_ctrl_color },
      { kind: "arrow", from: "d2", to: "d4", color: palette.mark_alt_color },
      { kind: "arrow", from: "h2", to: "h4", color: palette.mark_ctrl_alt_color },
    ]);
  }

  function choose(name, hex) {
    palette[name] = hex;
    rows.get(name).sync();
    drawPreview();
    clearTimeout(timers.get(name));
    status.textContent = "";
    timers.set(
      name,
      setTimeout(async () => {
        try {
          await updateSettings({ [name]: hex });
          status.textContent = "Saved";
        } catch (err) {
          showError(err);
        }
      }, SAVE_DELAY_MS),
    );
  }

  function row([name, label, hint]) {
    const input = h("input", {
      class: "hex",
      type: "text",
      maxlength: "7",
      spellcheck: "false",
      autocomplete: "off",
      placeholder: "rrggbb",
      "aria-label": `${label} colour as rrggbb`,
      dataset: { setting: name },
    });
    const swatches = PRESETS.map(([presetName, hex]) => {
      const b = h("button", {
        type: "button",
        class: "preset",
        title: `${presetName} ${hex}`,
        "aria-label": `${label}: ${presetName}`,
        dataset: { hex },
        onclick: () => choose(name, hex),
      });
      b.style.background = hex; // CSSOM, which the CSP allows (unlike a style attribute)
      return b;
    });
    input.addEventListener("input", () => {
      const hex = parseHex(input.value);
      input.setAttribute("aria-invalid", hex ? "false" : "true");
      if (hex) choose(name, hex);
    });
    input.addEventListener("blur", () => rows.get(name).sync()); // an unfinished value goes back to the saved one
    rows.set(name, {
      sync() {
        const hex = palette[name];
        if (document.activeElement !== input || parseHex(input.value) !== hex) input.value = hex.slice(1);
        input.setAttribute("aria-invalid", "false");
        for (const b of swatches) b.setAttribute("aria-pressed", String(b.dataset.hex === hex));
      },
    });
    rows.get(name).sync();
    return h(
      "div",
      { class: "mark-row" },
      h("div", { class: "mark-label" }, h("strong", {}, label), h("span", { class: "muted small" }, hint)),
      h("div", { class: "presets" }, swatches),
      h("label", { class: "hex-field" }, h("span", { class: "muted" }, "#"), input),
    );
  }

  const reset = h(
    "button",
    {
      type: "button",
      class: "small",
      onclick: async () => {
        const defaults = Object.fromEntries(ROWS.map(([name]) => [name, DEFAULTS[name]]));
        try {
          await updateSettings(defaults);
          Object.assign(palette, defaults);
          for (const r of rows.values()) r.sync();
          drawPreview();
          status.textContent = "Back to the defaults";
        } catch (err) {
          showError(err);
        }
      },
    },
    "Reset to defaults",
  );

  drawPreview();
  const card = h(
    "div",
    { class: "card" },
    h("h2", {}, "Board marks"),
    h(
      "p",
      { class: "muted small" },
      "The colours of what you draw on the board. Pick one or type any rrggbb; saved to your account.",
    ),
    h(
      "div",
      { class: "marks-layout" },
      h("div", { class: "mark-rows" }, ROWS.map(row)),
      h("div", { class: "mark-preview" }, preview.el, h("div", { class: "button-row" }, reset, status)),
    ),
  );
  return card;
}
