// The board: drawn from a FEN, moved by click or by drag. It never decides
// what is legal: the game page hands it the server's legal-move list
// (GET /games/{id}/legal-moves: {from, to, san, promotion}) and it offers
// exactly those, then hands the chosen move's SAN back to be sent.
//
// As on lichess and chess.com, a player can pick up any of their own pieces
// whenever the game is on (even out of turn, even one with no legal move), and
// a drop or click anywhere that is not a legal destination is simply ignored:
// the piece goes back and nothing is sent. The opponent's pieces never move.

import { h, clear } from "./ui.js";
import { isDark, parseFen, pieceSrc, squaresFrom } from "./fen.js";

const DRAG_THRESHOLD = 4; // px a pointer travels before a press becomes a drag
const PROMOTION_ORDER = ["Q", "N", "R", "B"];

/** Where the king lands for a castling SAN, and the rook square that also means it. */
function castleTargets(entry) {
  const rank = entry.from[1];
  if (entry.san.startsWith("0-0-0")) return { to: `c${rank}`, alias: `a${rank}`, rook: [`a${rank}`, `d${rank}`] };
  return { to: `g${rank}`, alias: `h${rank}`, rook: [`h${rank}`, `f${rank}`] };
}

export class Board {
  /**
   * @param {object} opts
   * @param {"white"|"black"} opts.orientation  which side is at the bottom
   * @param {boolean} opts.mini   a thumbnail: no coordinates, never interactive
   * @param {"w"|"b"|null} opts.player  whose pieces this viewer may pick up (null: a spectator)
   * @param {(san: string) => void} opts.onMove  called with the chosen move
   * @param {() => boolean} opts.autoQueen  asked at each promotion: queen without the picker?
   */
  constructor({ orientation = "white", mini = false, player = null, onMove = null, autoQueen = () => false } = {}) {
    this.autoQueen = autoQueen;
    this.orientation = orientation;
    this.mini = mini;
    this.player = player;
    this.onMove = onMove;
    this.enabled = false; // pieces may be picked up (a player, game in progress)
    this.el = h("div", { class: `board${mini ? " mini" : ""}` });
    this.position = { squares: new Map(), turn: "w" };
    this.lastMove = null;
    this.check = false;
    this.moves = null; // from -> Map(to -> [entries]); null when no move may be made
    this.aliases = new Map(); // "e1h1" -> "g1": dropping a king on its rook castles
    this.castles = new Map(); // "e1g1" -> rook [from, to], for drawing the move at once
    this.selected = null;
    this.drag = null;
    this.squareEls = new Map();
    this.build();
    if (onMove && !mini) {
      this.el.addEventListener("pointerdown", (ev) => this.pointerDown(ev));
      this.el.addEventListener("pointermove", (ev) => this.pointerMove(ev));
      this.el.addEventListener("pointerup", (ev) => this.pointerUp(ev));
      this.el.addEventListener("pointercancel", () => this.endDrag());
      this.el.addEventListener("contextmenu", (ev) => ev.preventDefault());
    }
  }

  build() {
    clear(this.el);
    this.squareEls.clear();
    squaresFrom(this.orientation).forEach((square, i) => {
      const el = h("div", { class: `sq${isDark(square) ? " dark" : ""}`, dataset: { square } });
      if (!this.mini) {
        if (i % 8 === 0) el.append(h("span", { class: "coord rank" }, square[1]));
        if (i >= 56) el.append(h("span", { class: "coord file" }, square[0]));
      }
      this.squareEls.set(square, el);
      this.el.append(el);
    });
  }

  /** Show a position. lastMove: {from, to} to highlight; check: whether the side to move is in check. */
  setPosition(fen, { lastMove = null, check = false } = {}) {
    this.position = parseFen(fen);
    this.lastMove = lastMove;
    this.check = check;
    this.render();
  }

  /** Let the player pick up their pieces (the game is on), or not (over, or a spectator). */
  setEnabled(on) {
    this.enabled = Boolean(on && this.player && this.onMove && !this.mini);
    if (!this.enabled) {
      this.selected = null;
      this.endDrag();
    }
    this.el.classList.toggle("interactive", this.enabled);
    this.render();
  }

  /** Whether the piece on a square is one this viewer may pick up. */
  canPick(square) {
    const piece = this.position.squares.get(square);
    return Boolean(this.enabled && piece && piece.color === this.player);
  }

  /**
   * Which moves count (the server's list), or none (null): not your turn. Pieces
   * stay pickable either way; this only decides where a drop does something.
   */
  setLegal(list) {
    if (this.selected && !this.canPick(this.selected)) this.selected = null;
    this.aliases.clear();
    this.castles.clear();
    if (!list || !list.length) {
      this.moves = null;
    } else {
      this.moves = new Map();
      for (const entry of list) {
        let to = entry.to;
        if (!to) {
          // Castling comes back with no destination: it is the king's two-square move.
          const c = castleTargets(entry);
          to = c.to;
          this.aliases.set(entry.from + c.alias, c.to);
          this.castles.set(entry.from + c.to, c.rook);
        }
        if (!this.moves.has(entry.from)) this.moves.set(entry.from, new Map());
        const targets = this.moves.get(entry.from);
        if (!targets.has(to)) targets.set(to, []);
        targets.get(to).push(entry);
      }
    }
    this.el.classList.toggle("has-moves", Boolean(this.moves));
    this.render();
  }

  flip() {
    this.orientation = this.orientation === "white" ? "black" : "white";
    this.build();
    this.render();
  }

  setOrientation(orientation) {
    if (orientation !== this.orientation) this.flip();
  }

  render() {
    const { squares, turn } = this.position;
    const targets = this.selected && this.moves ? this.moves.get(this.selected) : null;
    for (const [square, el] of this.squareEls) {
      const piece = squares.get(square);
      el.querySelector(".piece")?.remove();
      if (piece) el.append(h("img", { class: "piece", src: pieceSrc(piece), alt: "", draggable: "false" }));
      const cl = el.classList;
      cl.toggle("last", Boolean(this.lastMove && (this.lastMove.from === square || this.lastMove.to === square)));
      cl.toggle("check", Boolean(this.check && piece && piece.type === "K" && piece.color === turn));
      cl.toggle("selected", this.selected === square);
      cl.toggle("target", Boolean(targets && targets.has(square)));
      cl.toggle("occupied", Boolean(piece));
      cl.toggle("movable", this.canPick(square));
      cl.remove("hover");
    }
  }

  // --- Input ----------------------------------------------------------------

  squareAt(x, y) {
    const el = document.elementFromPoint(x, y)?.closest?.(".sq");
    return el && this.el.contains(el) ? el.dataset.square : null;
  }

  target(from, to) {
    if (!this.moves || !this.moves.has(from)) return null;
    const targets = this.moves.get(from);
    if (targets.has(to)) return to;
    const aliased = this.aliases.get(from + to);
    return aliased && targets.has(aliased) ? aliased : null;
  }

  pointerDown(ev) {
    if (ev.button !== 0 || !this.enabled || this.el.querySelector(".promotion")) return;
    const square = ev.target.closest(".sq")?.dataset.square;
    if (!square) return;
    if (this.selected) {
      const to = this.target(this.selected, square);
      if (to) {
        this.tryMove(this.selected, to);
        return;
      }
    }
    if (this.canPick(square)) {
      const wasSelected = this.selected === square;
      this.selected = square;
      this.render();
      this.drag = { from: square, x: ev.clientX, y: ev.clientY, moved: false, wasSelected, ghost: null };
      this.el.setPointerCapture(ev.pointerId);
      ev.preventDefault();
    } else if (this.selected) {
      this.selected = null;
      this.render();
    }
  }

  pointerMove(ev) {
    const drag = this.drag;
    if (!drag) return;
    if (!drag.moved) {
      if (Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y) < DRAG_THRESHOLD) return;
      drag.moved = true;
      const from = this.squareEls.get(drag.from);
      const size = from.getBoundingClientRect().width;
      const img = from.querySelector(".piece");
      if (!img) return;
      img.classList.add("ghost");
      drag.size = size;
      drag.ghost = h("img", { class: "drag-piece", src: img.src, alt: "", draggable: "false" });
      drag.ghost.style.width = `${size}px`;
      drag.ghost.style.height = `${size}px`;
      document.body.append(drag.ghost);
    }
    if (drag.ghost) {
      drag.ghost.style.transform = `translate(${ev.clientX - drag.size / 2}px, ${ev.clientY - drag.size / 2}px)`;
    }
    const over = this.squareAt(ev.clientX, ev.clientY);
    for (const [square, el] of this.squareEls) el.classList.toggle("hover", square === over && square !== drag.from);
  }

  pointerUp(ev) {
    const drag = this.drag;
    if (!drag) return;
    this.endDrag();
    if (drag.moved) {
      const over = this.squareAt(ev.clientX, ev.clientY);
      const to = over ? this.target(drag.from, over) : null;
      if (to) {
        this.tryMove(drag.from, to);
        return;
      }
      if (over !== drag.from) this.selected = null; // dropped elsewhere: put it back
    } else if (drag.wasSelected) {
      this.selected = null; // a second click on the same piece lets go of it
    }
    this.render();
  }

  endDrag() {
    if (!this.drag) return;
    this.drag.ghost?.remove();
    this.drag = null;
    for (const el of this.squareEls.values()) {
      el.classList.remove("hover");
      el.querySelector(".piece")?.classList.remove("ghost");
    }
  }

  async tryMove(from, to) {
    const entries = this.moves.get(from).get(to);
    let entry = entries[0];
    if (entries.length > 1) {
      // A promotion: with auto_queen on, the queen; otherwise ask.
      const queen = entries.find((e) => e.promotion === "Q");
      entry = queen && this.autoQueen() ? queen : await this.pickPromotion(from, to, entries);
    }
    if (!entry) {
      this.selected = null;
      this.render();
      return;
    }
    this.showMove(from, to, entry);
    this.onMove(entry.san);
  }

  /** Draw the move at once, before the server answers; its answer replaces this. */
  showMove(from, to, entry) {
    const squares = this.position.squares;
    const piece = squares.get(from);
    if (piece && piece.type === "P" && from[0] !== to[0] && !squares.has(to)) {
      squares.delete(`${to[0]}${from[1]}`); // en passant
    }
    const rook = this.castles.get(from + to);
    if (rook && squares.has(rook[0])) {
      squares.set(rook[1], squares.get(rook[0]));
      squares.delete(rook[0]);
    }
    squares.delete(from);
    if (piece) squares.set(to, entry.promotion ? { color: piece.color, type: entry.promotion } : piece);
    this.lastMove = { from, to };
    this.check = /[+#]$/.test(entry.san);
    this.position.turn = this.position.turn === "w" ? "b" : "w";
    this.selected = null;
    this.moves = null; // until the server's answer brings the next list
    this.el.classList.remove("has-moves");
    this.render();
  }

  /** Resolves to the chosen promotion's entry, or null if the picker is dismissed. */
  pickPromotion(from, to, entries) {
    return new Promise((resolve) => {
      const color = this.position.squares.get(from)?.color || "w";
      const order = this.squareEls.get(to) ? [...this.squareEls.keys()].indexOf(to) : 0;
      const col = order % 8;
      const top = order < 8;
      const shade = h("div", { class: "board-shade" });
      const picker = h("div", { class: "promotion" });
      picker.style.left = `${col * 12.5}%`;
      picker.style.width = "12.5%";
      picker.style.height = "50%";
      picker.style.top = top ? "0" : "50%";
      const types = top ? PROMOTION_ORDER : [...PROMOTION_ORDER].reverse();
      const done = (entry) => {
        shade.remove();
        picker.remove();
        resolve(entry);
      };
      for (const type of types) {
        const entry = entries.find((e) => e.promotion === type);
        if (!entry) continue;
        picker.append(
          h(
            "button",
            { type: "button", title: { Q: "Queen", N: "Knight", R: "Rook", B: "Bishop" }[type], onclick: () => done(entry) },
            h("img", { src: pieceSrc({ color, type }), alt: type, draggable: "false" }),
          ),
        );
      }
      shade.addEventListener("pointerdown", (ev) => {
        ev.stopPropagation();
        done(null);
      });
      picker.addEventListener("pointerdown", (ev) => ev.stopPropagation());
      this.el.append(shade, picker);
    });
  }
}

