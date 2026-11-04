// A player's page: their games in progress, their finished games, your record
// against them, and a button to challenge them.

import { get, post } from "../api.js";
import { gameRow } from "../cards.js";
import { formatDate, h, replace, showError, toast } from "../ui.js";

export const NAV = "";

const PAGE = 20;

export async function render(main, params, ctx, scope) {
  const me = ctx.me;
  const user = await get("/users", { username: params[0] });
  const isMe = user.id === me.id;
  const current = h("div", { class: "rows" });
  const finished = h("div", { class: "rows" });
  const more = h("button", { class: "small", hidden: true, onclick: () => loadFinished() }, "Show more");
  let before = null;

  const head = h(
    "div",
    { class: "card" },
    h(
      "div",
      { class: "profile-head" },
      h("h1", {}, user.username),
      user.role === "admin" ? h("span", { class: "badge" }, "admin") : null,
      user.disabled_at ? h("span", { class: "badge danger" }, "disabled") : null,
      h("span", { class: "muted small" }, `joined ${formatDate(user.created_at)}`),
    ),
  );
  const record = h("div", { class: "stats" });
  if (!isMe) head.append(h("p", {}), record, h("p", {}), challengeButtons());

  replace(
    main,
    head,
    h("div", { class: "card" }, h("h2", {}, "Playing now"), current),
    h("div", { class: "card" }, h("h2", {}, "Finished games"), finished, more),
  );

  function challengeButtons() {
    const row = h("div", { class: "button-row" });
    for (const color of ["random", "white", "black"]) {
      row.append(
        h(
          "button",
          {
            class: color === "random" ? "primary" : "",
            disabled: Boolean(user.disabled_at),
            onclick: async () => {
              try {
                await post("/challenges", { opponent_id: user.id, color });
                toast(`Challenge sent to ${user.username}`, { href: "#/", linkText: "Play" });
              } catch (err) {
                showError(err);
              }
            },
          },
          color === "random" ? `Challenge ${user.username}` : `as ${color === "white" ? "White" : "Black"}`,
        ),
      );
    }
    return row;
  }

  async function loadCurrent() {
    const { games } = await get("/games", { player_id: user.id });
    replace(current);
    if (!games.length) current.append(h("p", { class: "muted" }, "No games in progress."));
    for (const g of games) current.append(gameRow(g, user));
  }

  async function loadFinished() {
    const { games } = await get("/games/finished", { player_id: user.id, limit: PAGE, before });
    if (before === null && !games.length) finished.append(h("p", { class: "muted" }, "No finished games yet."));
    for (const g of games) finished.append(gameRow(g, user));
    if (games.length) before = games[games.length - 1].id;
    more.hidden = games.length < PAGE;
  }

  async function loadRecord() {
    const r = await get("/games/record", { player1: me.id, player2: user.id });
    replace(
      record,
      h("div", {}, h("strong", {}, String(r.player1_wins)), h("span", { class: "muted small" }, "your wins")),
      h("div", {}, h("strong", {}, String(r.draws)), h("span", { class: "muted small" }, "draws")),
      h("div", {}, h("strong", {}, String(r.player2_wins)), h("span", { class: "muted small" }, `${user.username}'s wins`)),
    );
  }

  scope.poll(() => loadCurrent().catch(() => {}), 15000, { whenLive: true });
  await Promise.all([loadCurrent(), loadFinished(), isMe ? null : loadRecord()]);
}
