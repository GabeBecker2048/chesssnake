// Small pieces several pages share: a game as a card with a mini board, and a
// game as a one-line row.

import { Board } from "./board.js";
import { h, outcomeFor, replace, resultText, resultToken, sideToMove, swatch, timeAgo } from "./ui.js";

/**
 * A card with a live mini board. `update(state, move)` redraws it; a move's
 * from/to (from a websocket event) is highlighted.
 */
export function gameCard(state, { me = null } = {}) {
  const mine = me && (state.white_id === me.id || state.black_id === me.id);
  const orientation = mine && state.black_id === me.id ? "black" : "white";
  const board = new Board({ orientation, mini: true });
  const top = h("div", { class: "names" });
  const bottom = h("div", { class: "names" });
  const meta = h("div", { class: "meta" });
  const el = h("a", { class: "game-card", href: `#/game/${state.id}` }, top, board.el, bottom, meta);
  let current = null;

  function update(next, move = null) {
    if (current && next.version < current.version) return;
    current = next;
    board.setPosition(next.fen, {
      lastMove: move ? { from: move.from, to: move.to } : null,
      check: Boolean(move && move.check),
    });
    const white = h("span", {}, swatch("white"), " ", next.white_name);
    const black = h("span", {}, swatch("black"), " ", next.black_name);
    replace(top, orientation === "white" ? black : white);
    replace(bottom, orientation === "white" ? white : black);
    const toMove = sideToMove(next.fen);
    let status;
    if (next.status !== 0) status = h("span", {}, resultToken(next));
    else if (mine && (toMove === "white") === (next.white_id === me.id)) status = h("span", { class: "badge turn" }, "Your turn");
    else status = h("span", {}, `${toMove === "white" ? next.white_name : next.black_name} to move`);
    replace(meta, status, h("span", {}, timeAgo(next.updated_at)));
  }

  update(state);
  return { el, update, get state() { return current; } };
}

/** One game as a row: opponent (from `forUser`'s side), colour, result, when. */
export function gameRow(state, forUser) {
  const isWhite = state.white_id === forUser.id;
  const opponent = isWhite ? state.black_name : state.white_name;
  let result;
  if (state.status === 0) result = h("span", { class: "badge" }, "In progress");
  else {
    const outcome = outcomeFor(state, forUser.id);
    result = h("span", { class: `badge ${outcome === "Won" ? "turn" : outcome === "Lost" ? "danger" : ""}`, title: resultText(state) }, outcome);
  }
  return h(
    "a",
    { class: "row", href: `#/game/${state.id}` },
    swatch(isWhite ? "white" : "black"),
    h("span", { class: "grow" }, "vs ", opponent),
    result,
    h("span", { class: "muted small" }, timeAgo(state.updated_at)),
  );
}
