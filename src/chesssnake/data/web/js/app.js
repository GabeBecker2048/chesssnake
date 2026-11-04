// Entry point: find out who is logged in, draw the top bar, and route.

import { LOGGED_OUT, clearToken, get, token } from "./api.js";
import { live } from "./live.js";
import { Scope, go, match } from "./router.js";
import { h, replace, toast } from "./ui.js";
import * as account from "./views/account.js";
import * as admin from "./views/admin.js";
import * as game from "./views/game.js";
import * as home from "./views/home.js";
import * as login from "./views/login.js";
import * as profile from "./views/profile.js";
import * as watch from "./views/watch.js";

const ROUTES = [
  [/^\/$/, home],
  [/^\/login$/, login],
  [/^\/game\/(\d+)$/, game],
  [/^\/watch$/, watch],
  [/^\/user\/([^/]+)$/, profile],
  [/^\/account$/, account],
  [/^\/admin$/, admin],
];

/** What every view gets: who is logged in, what the server allows, and how to change either. */
export const ctx = {
  me: null,
  info: { registration: "closed", websocket: false, version: "" },
  signedIn,
  signOut,
};

const main = document.getElementById("app");
let scope = null;

function setNav(name) {
  for (const a of document.querySelectorAll("[data-nav]")) a.classList.toggle("active", a.dataset.nav === name);
}

function drawTopBar() {
  const me = ctx.me;
  document.getElementById("nav").hidden = !me;
  document.getElementById("account").hidden = !me;
  document.getElementById("nav-admin").hidden = !(me && me.role === "admin");
  if (me) {
    const link = document.getElementById("nav-me");
    link.textContent = me.username;
    link.href = `#/user/${encodeURIComponent(me.username)}`;
  }
  drawLiveDot();
}

function drawLiveDot() {
  const dot = document.getElementById("live-dot");
  dot.classList.toggle("live", live.isLive);
  dot.classList.toggle("down", live.enabled && !live.isLive);
  dot.title = live.isLive
    ? "Live: moves appear as they are played"
    : live.enabled
      ? "Reconnecting: refreshing every few seconds meanwhile"
      : "This server has live updates off: refreshing every few seconds";
}

async function route() {
  if (scope) scope.dispose();
  scope = new Scope();
  window.scrollTo(0, 0);
  let found = match(ROUTES, location.hash);
  if (!ctx.me && (!found || found.view !== login)) {
    found = { view: login, params: [] };
  } else if (!found) {
    replace(main, h("div", { class: "card" }, h("h1", {}, "Not found"), h("a", { href: "#/" }, "Back to Play")));
    return;
  }
  setNav(found.view.NAV || "");
  replace(main, h("p", { class: "muted loading" }, "Loading…"));
  const mine = scope;
  try {
    await found.view.render(main, found.params, ctx, scope);
  } catch (err) {
    if (mine !== scope || !ctx.me) return; // navigated away, or the 401 already sent us to login
    replace(main, h("div", { class: "card" }, h("h1", {}, "Something went wrong"), h("p", { class: "error" }, err.message || String(err))));
  }
}

function signedIn(user) {
  ctx.me = user;
  live.start(ctx.info);
  drawTopBar();
  go(location.hash && location.hash !== "#/login" ? location.hash : "#/");
}

function signOut(message) {
  clearToken();
  live.stop();
  ctx.me = null;
  drawTopBar();
  if (message) toast(message, { kind: "error" });
  go("#/login");
}

// Events about the user that matter wherever they are on the site.
live.addEventListener("status", drawLiveDot);
live.addEventListener("challenge", (ev) => {
  const { event, challenge } = ev.detail;
  if (event === "created" && ctx.me && challenge.challenged_id === ctx.me.id && location.hash !== "#/" && location.hash !== "") {
    toast(`${challenge.challenger_name} challenged you`, { href: "#/", linkText: "See it" });
  }
});
live.addEventListener("game_started", (ev) => {
  const state = ev.detail.state;
  // Give the page that caused it (an accept, a rematch) a moment to open the game itself.
  setTimeout(() => {
    if (location.hash === `#/game/${state.id}` || !ctx.me) return;
    const opponent = state.white_id === ctx.me.id ? state.black_name : state.white_name;
    toast(`Your game against ${opponent} has started`, { href: `#/game/${state.id}`, linkText: "Play" });
  }, 500);
});
window.addEventListener(LOGGED_OUT, (ev) => {
  if (ctx.me) signOut(ev.detail || "Your session has ended; log in again");
});

async function boot() {
  try {
    ctx.info = await get("/info");
  } catch (err) {
    replace(main, h("div", { class: "card" }, h("h1", {}, "Cannot reach the server"), h("p", { class: "muted" }, err.message)));
    return;
  }
  if (token()) {
    try {
      ctx.me = await get("/auth/me");
      live.start(ctx.info);
    } catch {
      ctx.me = null; // a 401 cleared the token; anything else, log in again
    }
  }
  drawTopBar();
  window.addEventListener("hashchange", route);
  route();
}

boot();
