// Hash routing (#/game/41), so the server needs no fallback route, and a Scope
// per page that undoes everything the page set up (listeners, timers, game
// subscriptions) when the user navigates away.

import { live } from "./live.js";

export class Scope {
  constructor() {
    this.cleanups = [];
    this.alive = true;
  }

  /** addEventListener, removed when the page goes. */
  on(target, type, fn) {
    target.addEventListener(type, fn);
    this.cleanups.push(() => target.removeEventListener(type, fn));
  }

  /** live.addEventListener for a live event, handing the handler event.detail. */
  onLive(type, fn) {
    this.on(live, type, (ev) => this.alive && fn(ev.detail));
  }

  /**
   * Run fn every ms. With whenLive false (the default) it is a fallback: it is
   * skipped while the websocket is up, which already pushes every change.
   */
  poll(fn, ms, { whenLive = false } = {}) {
    const id = setInterval(() => {
      if (this.alive && !document.hidden && (whenLive || !live.isLive)) fn();
    }, ms);
    this.cleanups.push(() => clearInterval(id));
  }

  /** Follow a game over the websocket while this page is shown. */
  follow(gameId) {
    live.subscribe(gameId);
    this.cleanups.push(() => live.unsubscribe(gameId));
  }

  add(fn) {
    this.cleanups.push(fn);
  }

  dispose() {
    this.alive = false;
    for (const fn of this.cleanups.splice(0).reverse()) {
      try {
        fn();
      } catch {
        // a cleanup failing must not stop the others
      }
    }
  }
}

/** Match location.hash against [pattern, view] pairs: {view, params} or null. */
export function match(routes, hash) {
  const path = (hash || "").replace(/^#/, "") || "/";
  for (const [pattern, view] of routes) {
    const m = path.match(pattern);
    if (m) return { view, params: m.slice(1).map(decodeURIComponent) };
  }
  return null;
}

export function go(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = hash;
}
