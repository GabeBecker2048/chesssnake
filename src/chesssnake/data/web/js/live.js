// Live updates over /v1/ws (docs/websocket-api.md). One socket for the
// whole page, shared by every view: views subscribe to the games they show and
// listen for events; the socket re-subscribes everything after a reconnect.
//
// When the server has websockets off (info.websocket is false) nothing connects
// and `isLive` stays false: views then poll over REST instead, which is the
// whole fallback. Views check `isLive` on every tick, so a socket that drops
// turns polling back on until it reconnects.
//
// Events (dispatched on `live`, an EventTarget; the payload is event.detail):
//   game          {state, move, snapshot}   a followed game changed (versions only increase)
//   game_removed  {game}                    an admin deleted a followed game
//   game_started  {state}                   a game you play in began
//   challenge     {event, challenge}        a challenge to or from you, created or removed
//   status        {live}                    the socket went up or down
//   resync        {}                        reconnected: re-read anything not sent as a snapshot

import { LOGGED_OUT, clearToken, token } from "./api.js";

const BACKOFF_START = 1000;
const BACKOFF_MAX = 30000;
const PING_EVERY = 25000;
// Close codes after which reconnecting cannot help.
const FINAL = new Set([1000, 1009, 4400, 4403]);

class Live extends EventTarget {
  constructor() {
    super();
    this.enabled = false;
    this.ws = null;
    this.isLive = false;
    this.wanted = new Map(); // game id -> number of views following it
    this.seen = new Map(); // game id -> highest version delivered
    this.backoff = BACKOFF_START;
    this.timer = null;
    this.pinger = null;
    this.everReady = false;
  }

  /** Connect if the server has websockets on. Called after login. */
  start(info) {
    this.stop();
    this.enabled = Boolean(info && info.websocket);
    if (this.enabled) this.connect();
    else this.setLive(false);
  }

  /** Disconnect for good (logout). */
  stop() {
    this.enabled = false;
    clearTimeout(this.timer);
    clearInterval(this.pinger);
    if (this.ws) {
      const ws = this.ws;
      this.ws = null;
      ws.onclose = null;
      ws.close(1000);
    }
    this.wanted.clear();
    this.seen.clear();
    this.setLive(false);
  }

  subscribe(gameId) {
    const n = this.wanted.get(gameId) || 0;
    this.wanted.set(gameId, n + 1);
    if (n === 0 && this.isLive) this.send({ type: "subscribe", game: gameId });
  }

  unsubscribe(gameId) {
    const n = this.wanted.get(gameId) || 0;
    if (n <= 1) {
      this.wanted.delete(gameId);
      this.seen.delete(gameId);
      if (n === 1 && this.isLive) this.send({ type: "unsubscribe", game: gameId });
    } else {
      this.wanted.set(gameId, n - 1);
    }
  }

  connect() {
    if (!this.enabled || !token()) return;
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    let ws;
    try {
      ws = new WebSocket(`${scheme}//${location.host}/v1/ws`);
    } catch {
      this.retry();
      return;
    }
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: token() }));
    ws.onmessage = (ev) => this.receive(ev.data);
    ws.onclose = (ev) => this.closed(ev.code);
  }

  closed(code) {
    this.ws = null;
    clearInterval(this.pinger);
    this.setLive(false);
    if (code === 4401) {
      // The token was revoked, expired, or its user disabled.
      clearToken();
      window.dispatchEvent(new CustomEvent(LOGGED_OUT, { detail: "Your session has ended; log in again" }));
      return;
    }
    if (FINAL.has(code)) return; // polling continues; reconnecting cannot help
    this.retry();
  }

  retry() {
    clearTimeout(this.timer);
    if (!this.enabled) return;
    const wait = this.backoff;
    this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX);
    this.timer = setTimeout(() => this.connect(), wait);
  }

  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message));
  }

  receive(data) {
    let msg;
    try {
      msg = JSON.parse(data);
    } catch {
      return;
    }
    switch (msg.type) {
      case "ready":
        this.backoff = BACKOFF_START;
        this.seen.clear(); // fresh snapshots follow; there is no replay
        for (const gameId of this.wanted.keys()) this.send({ type: "subscribe", game: gameId });
        clearInterval(this.pinger);
        this.pinger = setInterval(() => this.send({ type: "ping" }), PING_EVERY);
        this.setLive(true);
        if (this.everReady) this.emit("resync", {});
        this.everReady = true;
        break;
      case "subscribed":
        this.deliver(msg.state, null, true);
        break;
      case "game":
        this.deliver(msg.state, msg.move, false, msg.legal_moves);
        break;
      case "game_removed":
        this.seen.delete(msg.game);
        this.emit("game_removed", { game: msg.game });
        break;
      case "game_started":
        this.emit("game_started", { state: msg.state });
        break;
      case "challenge":
        this.emit("challenge", { event: msg.event, challenge: msg.challenge });
        break;
      default:
        break; // pong, error: nothing to do
    }
  }

  // legalMoves: the next player's options, sent with a move since 0.15.1 (else undefined)
  deliver(state, move, snapshot, legalMoves) {
    if (!state || !this.wanted.has(state.id)) return;
    const last = this.seen.get(state.id) || 0;
    if (state.version <= last) return; // never backwards (the server promises it; this is cheap)
    this.seen.set(state.id, state.version);
    this.emit("game", { state, move, snapshot, legalMoves });
  }

  setLive(value) {
    if (this.isLive === value) return;
    this.isLive = value;
    this.emit("status", { live: value });
  }

  emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}

export const live = new Live();
