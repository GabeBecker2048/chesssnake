// Marks drawn on the board, chess.com style:
//
//   right-click a square        highlight it (filled, under the piece)
//   right-drag to another       an arrow (a knight's move bends into an L)
//   middle-click a square       a ring
//
// Doing the same again in the same colour removes it; in another colour,
// recolours it. A left click on the board clears everything. Marks belong to
// whoever draws them: nothing is sent anywhere, and spectators can draw too.
//
// Colour: Ctrl for green, Alt for blue, otherwise the mark's own default (red
// for a highlight, orange for an arrow or ring). Shift is deliberately unused:
// some browsers (Firefox) always open their own context menu on Shift +
// right-click, and no page can prevent it.
//
// Highlights are drawn in an <svg> under the pieces and arrows and rings in one
// over them, both in square units (viewBox 0 0 8 8) with pointer-events off.

import { squaresFrom } from "./fen.js";

const SVG = "http://www.w3.org/2000/svg";

export const COLORS = {
  red: "#e0442f",
  orange: "#f39a14",
  green: "#2e9b45",
  blue: "#2f6fd1",
};

const DEFAULT_COLOR = { square: "red", arrow: "orange", circle: "orange" };

/** The colour a mark gets from the modifier keys held as it is made. */
export function colorFor(ev, kind) {
  if (ev.ctrlKey || ev.metaKey) return "green";
  if (ev.altKey) return "blue";
  return DEFAULT_COLOR[kind];
}

// --- The context menu --------------------------------------------------------
//
// Each board stops the menu on itself. This also stops it for a moment after a
// right-drag ends anywhere, since on some systems the menu event fires on the
// mouse-up, which may land just off the board.

let suppressMenuUntil = 0;

export function suppressContextMenu(ms = 400) {
  suppressMenuUntil = performance.now() + ms;
}

document.addEventListener(
  "contextmenu",
  (ev) => {
    if (performance.now() < suppressMenuUntil) ev.preventDefault();
  },
  true,
);

// --- Shapes ------------------------------------------------------------------

/** A shape's identity, ignoring colour: what making it again toggles. */
function keyOf(shape) {
  return `${shape.kind}:${shape.from}${shape.to ? `-${shape.to}` : ""}`;
}

/**
 * Add a shape, recolour it, or remove it.
 * @returns {Array} the new list (the input is not changed)
 */
export function toggleShape(shapes, shape) {
  const key = keyOf(shape);
  const existing = shapes.find((s) => keyOf(s) === key);
  if (!existing) return [...shapes, shape];
  if (existing.color === shape.color) return shapes.filter((s) => s !== existing);
  return shapes.map((s) => (s === existing ? shape : s));
}

// --- Drawing ---------------------------------------------------------------------

/** Square name -> its top-left corner in board units, as seen from `orientation`. */
function corners(orientation) {
  const map = new Map();
  squaresFrom(orientation).forEach((square, i) => map.set(square, [i % 8, Math.floor(i / 8)]));
  return map;
}

function el(tag, attrs) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

/** A knight's jump (1 by 2): drawn as an L, the long leg first, the way the piece moves. */
function knightCorner([x1, y1], [x2, y2]) {
  const dx = Math.abs(x2 - x1);
  const dy = Math.abs(y2 - y1);
  if (!((dx === 1 && dy === 2) || (dx === 2 && dy === 1))) return null;
  return dx > dy ? [x2, y1] : [x1, y2];
}

const LINE = 0.18; // stroke width, in squares
const HEAD_LENGTH = 0.45;
const HEAD_WIDTH = 0.5;
const RING = 0.44;
const RING_WIDTH = 0.08;

function arrow(group, from, to, color, opacity) {
  const corner = knightCorner(from, to);
  const tail = corner || from;
  const len = Math.hypot(to[0] - tail[0], to[1] - tail[1]);
  const [ux, uy] = [(to[0] - tail[0]) / len, (to[1] - tail[1]) / len];
  // The head's tip stops a little short of the centre, and the shaft at the head's base.
  const tip = [to[0] - ux * 0.1, to[1] - uy * 0.1];
  const base = [tip[0] - ux * HEAD_LENGTH, tip[1] - uy * HEAD_LENGTH];
  const points = corner ? [from, corner, base] : [from, base];
  group.append(
    el("polyline", {
      points: points.map((p) => p.join(",")).join(" "),
      fill: "none",
      stroke: COLORS[color],
      "stroke-width": LINE,
      "stroke-linecap": "butt",
      "stroke-linejoin": "round",
      opacity,
    }),
  );
  const [px, py] = [-uy * (HEAD_WIDTH / 2), ux * (HEAD_WIDTH / 2)];
  group.append(
    el("polygon", {
      points: [tip, [base[0] + px, base[1] + py], [base[0] - px, base[1] - py]].map((p) => p.join(",")).join(" "),
      fill: COLORS[color],
      opacity,
    }),
  );
}

/** The two overlay elements a board appends once: highlights under the pieces, the rest over them. */
export function createLayers() {
  return {
    under: el("svg", { class: "drawing under", viewBox: "0 0 8 8", "aria-hidden": "true" }),
    over: el("svg", { class: "drawing over", viewBox: "0 0 8 8", "aria-hidden": "true" }),
  };
}

/**
 * Draw `shapes` (and the arrow being dragged, `preview`, fainter) into `layers`.
 * Shapes are by square name, so flipping the board only needs a redraw.
 */
export function renderShapes(layers, shapes, orientation, preview = null) {
  for (const layer of [layers.under, layers.over]) while (layer.firstChild) layer.firstChild.remove();
  const at = corners(orientation);
  const all = shapes.map((s) => [s, 0.85]);
  if (preview) all.push([preview, 0.55]);
  for (const [shape, opacity] of all) {
    const corner = at.get(shape.from);
    if (!corner) continue;
    const centre = [corner[0] + 0.5, corner[1] + 0.5];
    if (shape.kind === "square") {
      layers.under.append(el("rect", { x: corner[0], y: corner[1], width: 1, height: 1, fill: COLORS[shape.color], opacity: 0.75 }));
    } else if (shape.kind === "circle") {
      layers.over.append(
        el("circle", { cx: centre[0], cy: centre[1], r: RING, fill: "none", stroke: COLORS[shape.color], "stroke-width": RING_WIDTH, opacity }),
      );
    } else if (shape.kind === "arrow") {
      const to = at.get(shape.to);
      if (to) arrow(layers.over, centre, [to[0] + 0.5, to[1] + 0.5], shape.color, opacity);
    }
  }
}
