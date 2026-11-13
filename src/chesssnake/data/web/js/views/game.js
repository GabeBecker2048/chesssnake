// One game, for its players and for spectators: the board, the moves, and
// whatever the viewer may do (move, draw, resign, rematch).

import { ApiError, api, del, get, post } from "../api.js";
import { Board } from "../board.js";
import { setting } from "../settings.js";
import { go } from "../router.js";
import { confirmAction, copy, h, replace, resultText, resultToken, showError, sideToMove, swatch, toast } from "../ui.js";

export const NAV = "";

export async function render(main, params, ctx, scope) {
  const gameId = Number(params[0]);
  const me = ctx.me;
  let state = await get(`/games/${gameId}`);
  let sans = (await get(`/games/${gameId}/history`)).moves.map((m) => m.san);
  const myColor = state.white_id === me.id ? "white" : state.black_id === me.id ? "black" : null;
  const opponentId = myColor === "white" ? state.black_id : state.white_id;
  let lastMove = null;
  // {version, moves}: legal moves that arrived with a move event, so the player to
  // move need not ask for them. Used only for the version they came with.
  let pushedLegal = null;
  let sending = false;
  let newerGame = null; // a rematch that has started
  let rematch = null; // {kind: "incoming"|"outgoing", challenge}

  const board = new Board({
    orientation: myColor || "white",
    player: myColor ? myColor[0] : null, // "w" / "b"
    onMove: myColor ? sendMove : null,
    autoQueen: () => setting("auto_queen"), // read at each promotion, so a change applies at once
  });
  const topBar = h("div", { class: "player-bar" });
  const bottomBar = h("div", { class: "player-bar" });
  const status = h("div", { class: "status", role: "status" });
  const moveList = h("div", { class: "moves", "aria-label": "Moves" });
  const actions = h("div", { class: "button-row" });
  const tools = h(
    "div",
    { class: "button-row" },
    h("button", { class: "small", onclick: () => { board.flip(); drawBars(); } }, "Flip board"),
    h("button", { class: "small", onclick: copyPgn }, "Copy PGN"),
    h("button", { class: "small", onclick: downloadPgn }, "Download PGN"),
  );
  const note = h("p", { class: "muted small" });

  replace(
    main,
    h(
      "div",
      { class: "game-layout" },
      h("div", { class: "board-column" }, topBar, board.el, bottomBar),
      h(
        "aside",
        { class: "side-panel card" },
        status,
        moveList,
        actions,
        tools,
        note,
      ),
    ),
  );

  // --- Drawing -------------------------------------------------------------------

  function playerBar(color) {
    const name = color === "white" ? state.white_name : state.black_name;
    const toMove = state.status === 0 && sideToMove(state.fen) === color;
    const offered = state.draw !== null && state.draw === (color === "white" ? 0 : 1);
    return [
      swatch(color),
      h("a", { class: "name", href: `#/user/${encodeURIComponent(name)}` }, name),
      h("span", { class: "grow" }),
      offered ? h("span", { class: "badge warn" }, "offers a draw") : null,
      toMove ? h("span", { class: "badge turn" }, "to move") : null,
    ];
  }

  function drawBars() {
    const bottom = board.orientation;
    const top = bottom === "white" ? "black" : "white";
    replace(topBar, playerBar(top));
    replace(bottomBar, playerBar(bottom));
    topBar.classList.toggle("to-move", state.status === 0 && sideToMove(state.fen) === top);
    bottomBar.classList.toggle("to-move", state.status === 0 && sideToMove(state.fen) === bottom);
  }

  function drawStatus() {
    const toMove = sideToMove(state.fen);
    if (state.status !== 0) {
      replace(status, `${resultToken(state)} · ${resultText(state)}`);
    } else if (myColor) {
      replace(status, toMove === myColor ? "Your move" : `Waiting for ${toMove === "white" ? state.white_name : state.black_name}`);
    } else {
      replace(status, `${toMove === "white" ? state.white_name : state.black_name} to move`, h("span", { class: "muted small" }, " · spectating"));
    }
  }

  function drawMoves() {
    replace(moveList);
    if (!sans.length) moveList.append(h("span", { class: "empty" }, "No moves yet"));
    for (let i = 0; i < sans.length; i += 2) {
      moveList.append(h("span", { class: "num" }, `${i / 2 + 1}.`));
      moveList.append(h("span", { class: i === sans.length - 1 ? "latest" : "" }, pretty(sans[i])));
      moveList.append(h("span", { class: i + 1 === sans.length - 1 ? "latest" : "" }, sans[i + 1] ? pretty(sans[i + 1]) : ""));
    }
    moveList.scrollTop = moveList.scrollHeight;
  }

  function drawActions() {
    const buttons = [];
    const inPlay = state.status === 0;
    if (myColor && inPlay) {
      const mine = myColor === "white" ? 0 : 1;
      if (state.draw === null) {
        buttons.push(h("button", { onclick: () => act("draw/offer", "Draw offered") }, "Offer draw"));
      } else if (state.draw === mine) {
        buttons.push(h("button", { disabled: true }, "Draw offered"));
      } else {
        buttons.push(h("button", { class: "primary", onclick: () => act("draw/accept") }, "Accept draw"));
        buttons.push(h("button", { onclick: () => act("draw/decline", "Draw declined") }, "Decline draw"));
      }
      buttons.push(h("button", { class: "danger", onclick: resign }, "Resign"));
    } else if (myColor && !inPlay) {
      if (newerGame) {
        buttons.push(h("button", { class: "primary", onclick: () => go(`#/game/${newerGame}`) }, "Go to the new game"));
      } else if (rematch && rematch.kind === "incoming") {
        buttons.push(h("button", { class: "primary", onclick: acceptRematch }, "Accept rematch"));
      } else if (rematch && rematch.kind === "outgoing") {
        buttons.push(h("button", { disabled: true }, "Rematch offered"));
        buttons.push(h("button", { onclick: cancelRematch }, "Cancel"));
      } else {
        buttons.push(h("button", { class: "primary", onclick: offerRematch }, "Rematch"));
      }
    }
    replace(actions, buttons);
    actions.hidden = !buttons.length;
  }

  async function drawBoard() {
    const check = /[+#]$/.test(sans[sans.length - 1] || "");
    board.setPosition(state.fen, { lastMove, check });
    board.setEnabled(Boolean(myColor) && state.status === 0);
    let legal = null;
    if (myColor && state.status === 0 && sideToMove(state.fen) === myColor) {
      if (pushedLegal && pushedLegal.version === state.version) {
        legal = pushedLegal.moves; // sent with the opponent's move: no request needed
      } else {
        // page load, polling, a snapshot, a draw offer: ask, as before 0.15.1
        const asked = state.version;
        try {
          legal = (await get(`/games/${gameId}/legal-moves`)).moves;
        } catch {
          legal = null;
        }
        if (asked !== state.version || !scope.alive) return; // the position moved on meanwhile
      }
    }
    board.setLegal(legal);
  }

  function draw() {
    drawBars();
    drawStatus();
    drawMoves();
    drawActions();
    drawBoard();
    note.textContent = myColor ? "" : "You are watching this game.";
  }

  // --- Changes -------------------------------------------------------------------

  /** Take a newer state (from our own request, the socket, or a poll). */
  async function apply(next, move = null) {
    if (next.version <= state.version) return;
    const wasOver = state.status !== 0;
    if (move && next.version === state.version + 1) {
      sans.push(move.san);
      lastMove = move.from && move.to ? { from: move.from, to: move.to } : null;
    } else if (next.fen !== state.fen) {
      // Missed something (a poll, a reconnect): read the moves again.
      const history = (await get(`/games/${gameId}/history`)).moves.map((m) => m.san);
      if (next.version <= state.version) return; // something newer was applied while we read
      sans = history;
      lastMove = null;
    }
    state = next;
    draw();
    if (!wasOver && state.status !== 0) {
      toast(resultText(state));
      findRematch();
    }
  }

  async function refresh() {
    try {
      await apply(await get(`/games/${gameId}`));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) gone();
    }
  }

  async function sendMove(san) {
    if (sending) return;
    sending = true;
    try {
      const result = await post(`/games/${gameId}/moves`, { move: san, expected_version: state.version });
      await apply(result.state, { san: result.san, from: result.from, to: result.to });
    } catch (err) {
      if (!(err instanceof ApiError && err.type === "VersionConflictError")) showError(err);
      await refresh();
      drawBoard(); // put the piece back if the move did not happen
    } finally {
      sending = false;
    }
  }

  async function act(path, message = null) {
    try {
      const next = await post(`/games/${gameId}/${path}`, { expected_version: state.version });
      await apply(next);
      if (message) toast(message);
    } catch (err) {
      showError(err);
      refresh();
    }
  }

  async function resign() {
    if (await confirmAction("Resign?", "The game ends and your opponent wins.", "Resign")) act("resign");
  }

  // --- Rematch: the same three steps as `chesssnake play`'s `new` ----------------------

  async function findRematch() {
    if (!myColor || state.status === 0) return;
    try {
      const { games } = await get("/games/between", {
        player1: state.white_id,
        player2: state.black_id,
        group_id: state.group_id,
        status: "active",
      });
      const newer = games.find((g) => g.id > gameId);
      newerGame = newer ? newer.id : null;
      const { challenges } = await get("/challenges");
      const c = challenges.find(
        (x) =>
          x.group_id === state.group_id &&
          ((x.challenger_id === opponentId && x.challenged_id === me.id) || (x.challenger_id === me.id && x.challenged_id === opponentId)),
      );
      rematch = c ? { kind: c.challenger_id === me.id ? "outgoing" : "incoming", challenge: c } : null;
    } catch {
      // the buttons stay as they were
    }
    drawActions();
  }

  async function offerRematch() {
    try {
      // Colours swapped, in the same group, as the CLI does.
      const color = myColor === "white" ? "black" : "white";
      const c = await post("/challenges", { opponent_id: opponentId, group_id: state.group_id, color });
      rematch = { kind: "outgoing", challenge: c };
      drawActions();
    } catch (err) {
      showError(err);
      findRematch();
    }
  }

  async function acceptRematch() {
    try {
      const next = await post(`/challenges/${rematch.challenge.id}/accept`);
      go(`#/game/${next.id}`);
    } catch (err) {
      showError(err);
      findRematch();
    }
  }

  async function cancelRematch() {
    try {
      await del(`/challenges/${rematch.challenge.id}`);
    } catch (err) {
      showError(err);
    }
    findRematch();
  }

  // --- PGN ----------------------------------------------------------------------------

  async function pgnText() {
    return api("GET", `/games/${gameId}/pgn`, undefined, { asText: true });
  }

  async function copyPgn() {
    try {
      copy(await pgnText());
    } catch (err) {
      showError(err);
    }
  }

  async function downloadPgn() {
    try {
      const url = URL.createObjectURL(new Blob([await pgnText()], { type: "application/x-chess-pgn" }));
      const a = h("a", { href: url, download: `chesssnake-${gameId}.pgn` });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      showError(err);
    }
  }

  function gone() {
    toast("This game was deleted by an administrator", { kind: "error" });
    go("#/");
  }

  // --- Live --------------------------------------------------------------------------

  scope.follow(gameId);
  scope.onLive("game", ({ state: next, move, legalMoves }) => {
    if (next.id !== gameId) return;
    if (legalMoves) pushedLegal = { version: next.version, moves: legalMoves };
    apply(next, move);
  });
  scope.onLive("game_removed", ({ game }) => {
    if (game === gameId) gone();
  });
  scope.onLive("game_started", ({ state: next }) => {
    const samePlayers =
      next.group_id === state.group_id &&
      [next.white_id, next.black_id].sort().join() === [state.white_id, state.black_id].sort().join();
    if (myColor && samePlayers && next.id > gameId) {
      newerGame = next.id;
      rematch = null;
      drawActions();
    }
  });
  scope.onLive("challenge", () => findRematch());
  scope.onLive("resync", () => {
    refresh();
    findRematch();
  });
  // Without the socket: the game every 5 s, and once it is over, rematch news too.
  scope.poll(() => {
    refresh();
    if (state.status !== 0) findRematch();
  }, 5000);

  draw();
  findRematch();
}

/** Show the engine's castling notation (0-0) the way players write it (O-O). */
function pretty(san) {
  return san.replace(/^0-0-0/, "O-O-O").replace(/^0-0/, "O-O");
}
