// DOM helpers. Text only ever goes in through textContent, never parsed as HTML, so
// a username or an error message can never become markup. The page's CSP
// forbids inline script anyway; this is the other half of keeping the token safe.

/**
 * Build an element: h("a", {href: "#/", class: "x", onclick: fn}, "text", child).
 * Children may be strings, nodes, arrays, or null/false (skipped).
 */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2), value);
    } else if (key === "class") {
      el.className = value;
    } else if (key === "dataset") {
      Object.assign(el.dataset, value);
    } else if (key in el && typeof value !== "string") {
      el[key] = value; // checked, disabled, value, hidden ...
    } else {
      el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(el, child);
    else el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

export function replace(el, ...children) {
  clear(el);
  append(el, children);
  return el;
}

// --- Toasts -------------------------------------------------------------------

export function toast(message, { kind = "info", href = null, linkText = "Open", timeout = 6000 } = {}) {
  const box = document.getElementById("toasts");
  const close = () => item.remove();
  const item = h(
    "div",
    { class: `toast ${kind === "error" ? "error" : ""}`, role: kind === "error" ? "alert" : "status" },
    h("span", { class: "grow" }, message),
    href ? h("a", { href, onclick: close }, linkText) : null,
    h("button", { class: "small link", onclick: close, "aria-label": "Dismiss" }, "✕"),
  );
  box.append(item);
  if (timeout) setTimeout(close, timeout);
  return item;
}

export function showError(err) {
  toast(err && err.message ? err.message : String(err), { kind: "error" });
}

// --- Dialogs ------------------------------------------------------------------

/**
 * A modal form. Resolves to {name: value} on submit, or null when cancelled.
 * fields: [{name, label, type = "text", value, required, autocomplete}]
 */
export function dialog({ title, text = null, fields = [], submit = "OK", danger = false }) {
  return new Promise((resolve) => {
    const inputs = fields.map((f) =>
      h("input", {
        name: f.name,
        type: f.type || "text",
        value: f.value ?? "",
        required: f.required !== false,
        autocomplete: f.autocomplete || "off",
        min: f.min,
        max: f.max,
      }),
    );
    const form = h(
      "form",
      { method: "dialog", class: "stack" },
      h("h2", {}, title),
      text ? h("p", { class: "muted" }, text) : null,
      fields.map((f, i) => h("label", {}, f.label, inputs[i])),
      h(
        "div",
        { class: "button-row" },
        h("button", { type: "submit", class: danger ? "primary danger" : "primary", value: "ok" }, submit),
        h("button", { type: "button", onclick: () => finish(null) }, "Cancel"),
      ),
    );
    const dlg = h("dialog", {}, form);
    let done = false;
    function finish(result) {
      if (done) return;
      done = true;
      dlg.close();
      dlg.remove();
      resolve(result);
    }
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const values = {};
      fields.forEach((f, i) => (values[f.name] = inputs[i].value));
      finish(values);
    });
    dlg.addEventListener("cancel", () => finish(null));
    document.body.append(dlg);
    dlg.showModal();
    (inputs[0] || form.querySelector("button[type=submit]")).focus();
  });
}

export async function confirmAction(title, text, submit = "Confirm") {
  return (await dialog({ title, text, submit, danger: true })) !== null;
}

/** Show a secret once (a new api token), with a copy button. */
export function revealSecret(title, text, secret) {
  const dlg = h(
    "dialog",
    {},
    h("h2", {}, title),
    h("p", { class: "muted" }, text),
    h("code", { class: "secret" }, secret),
    h(
      "div",
      { class: "button-row" },
      h("button", { class: "primary", onclick: () => copy(secret) }, "Copy"),
      h("button", { onclick: () => { dlg.close(); dlg.remove(); } }, "Done"),
    ),
  );
  document.body.append(dlg);
  dlg.showModal();
}

export async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied");
  } catch {
    toast("Could not copy: select the text and copy it yourself", { kind: "error" });
  }
}

// --- Words for things -----------------------------------------------------------

const TERMINATIONS = {
  checkmate: "checkmate",
  resignation: "resignation",
  stalemate: "stalemate",
  threefold: "threefold repetition",
  fifty_move: "the fifty-move rule",
  insufficient_material: "insufficient material",
  agreement: "agreement",
};

export function resultToken(state) {
  return { 1: "1-0", 2: "0-1", 3: "½-½" }[state.status] || "*";
}

/** "White won by checkmate", "Draw by agreement", or "" while in play. */
export function resultText(state) {
  const why = TERMINATIONS[state.termination] || state.termination;
  const how = why ? ` by ${why}` : "";
  if (state.status === 1) return `${state.white_name} won${how}`;
  if (state.status === 2) return `${state.black_name} won${how}`;
  if (state.status === 3) return `Draw${how}`;
  return "";
}

/** From one player's side: "Won", "Lost", "Draw". */
export function outcomeFor(state, userId) {
  if (state.status === 3) return "Draw";
  const whiteWon = state.status === 1;
  const isWhite = state.white_id === userId;
  return whiteWon === isWhite ? "Won" : "Lost";
}

export function sideToMove(fen) {
  return fen.split(" ")[1] === "b" ? "black" : "white";
}

export function timeAgo(iso) {
  if (!iso) return "";
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (seconds < 60) return "just now";
  const units = [
    [60, "minute"],
    [3600, "hour"],
    [86400, "day"],
    [604800, "week"],
    [2629800, "month"],
    [31557600, "year"],
  ];
  let label = "";
  for (const [size, name] of units) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      label = `${n} ${name}${n === 1 ? "" : "s"} ago`;
    }
  }
  return label;
}

/** The same, compact, for tight spaces: "now", "5m", "2h", "3d", "2w", "4mo", "1y". */
export function shortAgo(iso) {
  if (!iso) return "";
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  const units = [
    [31557600, "y"],
    [2629800, "mo"],
    [604800, "w"],
    [86400, "d"],
    [3600, "h"],
    [60, "m"],
  ];
  for (const [size, name] of units) if (seconds >= size) return `${Math.floor(seconds / size)}${name}`;
  return "now";
}

export function formatDate(iso) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "";
}

export function swatch(color) {
  return h("span", { class: `swatch ${color}`, title: color });
}

export function userLink(name) {
  return h("a", { href: `#/user/${encodeURIComponent(name)}` }, name);
}
