// Watch: every game in progress as a live mini board, and the latest results.

import { get } from "../api.js";
import { gameCard } from "../cards.js";
import { h, replace, resultText, resultToken, timeAgo } from "../ui.js";
import { followSet } from "./home.js";

export const NAV = "watch";

const SHOWN = 24;

export async function render(main, _params, ctx, scope) {
  const grid = h("div", { class: "game-grid" });
  const finished = h("div", { class: "rows" });
  const cards = new Map();
  const follow = followSet(scope);

  replace(
    main,
    h(
      "div",
      {},
      h("div", { class: "card" }, h("h2", {}, "Games in progress"), grid),
      h("div", { class: "card" }, h("h2", {}, "Recently finished"), finished),
    ),
  );

  async function load() {
    const [{ games }, recent] = await Promise.all([
      get("/games/live", { limit: SHOWN }),
      get("/games/finished", { limit: 10 }),
    ]);
    // Keep the cards already shown (and their highlights); add new games, drop finished ones.
    const ids = new Set(games.map((g) => g.id));
    for (const [id, card] of cards) {
      if (!ids.has(id)) {
        card.el.remove();
        cards.delete(id);
      }
    }
    for (const state of games) {
      const card = cards.get(state.id);
      if (card) card.update(state);
      else {
        const made = gameCard(state, { me: ctx.me });
        cards.set(state.id, made);
        grid.append(made.el);
      }
    }
    if (!games.length) replace(grid, h("p", { class: "muted" }, "Nobody is playing right now."));
    else grid.querySelector("p.muted")?.remove();
    follow(games.map((g) => g.id));

    replace(finished);
    if (!recent.games.length) finished.append(h("p", { class: "muted" }, "No finished games yet."));
    for (const g of recent.games) {
      finished.append(
        h(
          "a",
          { class: "row", href: `#/game/${g.id}` },
          h("span", { class: "grow" }, `${g.white_name} vs ${g.black_name}`),
          h("span", { class: "badge", title: resultText(g) }, resultToken(g)),
          h("span", { class: "muted small" }, timeAgo(g.updated_at)),
        ),
      );
    }
  }

  scope.onLive("game", ({ state, move }) => cards.get(state.id)?.update(state, move));
  scope.onLive("resync", () => load().catch(() => {}));
  // New games have no event for spectators, so the list is re-read even while
  // live; without the socket this is also what moves the boards (more often).
  scope.poll(() => load().catch(() => {}), 15000, { whenLive: true });
  scope.poll(() => load().catch(() => {}), 5000);

  await load();
}
