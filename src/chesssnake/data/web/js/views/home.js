// Play: your games in progress, your challenges, and a form to challenge someone.

import { del, get, post } from "../api.js";
import { gameCard } from "../cards.js";
import { live } from "../live.js";
import { go } from "../router.js";
import { h, replace, shortAgo, showError, swatch, timeAgo, toast } from "../ui.js";

export const NAV = "play";

const OPPOSITE = { white: "black", black: "white", random: "random" };

/** Keeps a set of games followed over the websocket in step with a list that is re-read. */
export function followSet(scope) {
  const followed = new Set();
  scope.add(() => {
    for (const id of followed) live.unsubscribe(id);
    followed.clear();
  });
  return (ids) => {
    const next = new Set(ids);
    for (const id of followed) if (!next.has(id)) live.unsubscribe(id);
    for (const id of next) if (!followed.has(id)) live.subscribe(id);
    followed.clear();
    for (const id of next) followed.add(id);
  };
}

export async function render(main, _params, ctx, scope) {
  const me = ctx.me;
  const gamesBox = h("div", { class: "game-grid" });
  const challengesBox = h("div", { class: "challenges" });
  const cards = new Map(); // game id -> card
  const awaiting = new Set(); // opponents challenged from this page: open the game when they accept
  const follow = followSet(scope);

  replace(
    main,
    h(
      "div",
      { class: "columns" },
      h("section", {}, h("div", { class: "card" }, h("h2", {}, "Your games"), gamesBox)),
      h("aside", {}, challengeForm(), h("div", { class: "card" }, h("h2", {}, "Challenges"), challengesBox)),
    ),
  );

  async function loadGames() {
    const { games } = await get("/games");
    replace(gamesBox);
    cards.clear();
    if (!games.length) {
      gamesBox.append(h("p", { class: "muted" }, "No games in progress. Challenge someone, or ", h("a", { href: "#/watch" }, "watch a game"), "."));
    }
    // Games where it is your move first.
    const yours = (g) => (g.fen.split(" ")[1] === "w") === (g.white_id === me.id);
    games.sort((a, b) => Number(yours(b)) - Number(yours(a)));
    for (const state of games) {
      const card = gameCard(state, { me });
      cards.set(state.id, card);
      gamesBox.append(card.el);
    }
    follow(games.map((g) => g.id));
  }

  async function loadChallenges() {
    const { challenges } = await get("/challenges");
    replace(challengesBox);
    if (!challenges.length) challengesBox.append(h("p", { class: "muted" }, "No pending challenges."));
    for (const c of challenges) challengesBox.append(challengeRow(c));
  }

  /** One challenge: who and what on the left, two lines that wrap; its buttons on the right. */
  function challengeRow(c) {
    const incoming = c.challenged_id === me.id;
    const other = incoming ? c.challenger_name : c.challenged_name;
    const mine = incoming ? OPPOSITE[c.color] : c.color; // the colour this user would play
    const who = h("a", { class: "who", href: `#/user/${encodeURIComponent(other)}` }, other);
    const colour =
      mine === "random"
        ? h("span", { class: "nowrap" }, h("span", { class: "swatch random" }), " Random colour")
        : h("span", { class: "nowrap" }, swatch(mine), ` You play ${mine}`);
    const text = h(
      "div",
      { class: "challenge-text" },
      h("div", {}, incoming ? [who, " challenges you"] : ["Waiting for ", who]),
      h("div", { class: "muted small" }, colour, c.created_at ? h("span", { class: "nowrap", title: timeAgo(c.created_at) }, ` · ${shortAgo(c.created_at)}`) : null),
    );
    let buttons;
    if (incoming) {
      const accept = h("button", { class: "small primary", onclick: async () => {
        accept.disabled = true;
        try {
          const state = await post(`/challenges/${c.id}/accept`);
          go(`#/game/${state.id}`);
        } catch (err) {
          showError(err);
          accept.disabled = false;
          loadChallenges();
        }
      } }, "Accept");
      buttons = [accept, h("button", { class: "small", onclick: () => remove(c, "Declined") }, "Decline")];
    } else {
      buttons = [h("button", { class: "small", onclick: () => remove(c, "Withdrawn") }, "Cancel")];
    }
    return h("div", { class: "challenge" }, text, h("div", { class: "challenge-actions" }, buttons));
  }


  async function remove(c, message) {
    try {
      await del(`/challenges/${c.id}`);
      toast(message);
    } catch (err) {
      showError(err);
    }
    loadChallenges();
  }

  function challengeForm() {
    const list = h("datalist", { id: "user-suggestions" });
    const username = h("input", { name: "opponent", list: "user-suggestions", autocomplete: "off", required: true, placeholder: "Username" });
    const error = h("p", { class: "error", role: "alert" });
    const submit = h("button", { type: "submit", class: "primary" }, "Challenge");
    const colors = h(
      "div",
      { class: "segmented", role: "radiogroup", "aria-label": "Your colour" },
      ["random", "white", "black"].map((value) =>
        h("label", {}, h("input", { type: "radio", name: "color", value, checked: value === "random" }), h("span", {}, value === "random" ? "Random" : value === "white" ? "White" : "Black")),
      ),
    );
    let timer = null;
    username.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = username.value.trim();
        if (!q) return;
        try {
          const { users } = await get("/users/search", { q, limit: 8 });
          replace(list, users.filter((u) => u.id !== me.id && !u.disabled_at).map((u) => h("option", { value: u.username })));
        } catch {
          // suggestions are a nicety
        }
      }, 200);
    });
    const form = h(
      "form",
      { class: "card stack", onsubmit: async (ev) => {
        ev.preventDefault();
        error.textContent = "";
        submit.disabled = true;
        try {
          const opponent = await get("/users", { username: username.value.trim() });
          if (opponent.id === me.id) throw new Error("You cannot challenge yourself");
          const color = form.querySelector("input[name=color]:checked").value;
          await post("/challenges", { opponent_id: opponent.id, color });
          awaiting.add(opponent.id);
          toast(`Challenge sent to ${opponent.username}`);
          username.value = "";
          loadChallenges();
        } catch (err) {
          error.textContent = err.message;
        } finally {
          submit.disabled = false;
        }
      } },
      h("h2", {}, "Challenge someone"),
      h("label", {}, "Opponent", username),
      list,
      h("div", { class: "stack" }, h("span", { class: "muted small" }, "You play"), colors),
      error,
      submit,
    );
    return form;
  }

  scope.onLive("challenge", () => loadChallenges().catch(() => {}));
  scope.onLive("game_started", ({ state }) => {
    const opponent = state.white_id === me.id ? state.black_id : state.white_id;
    if (awaiting.has(opponent)) {
      go(`#/game/${state.id}`); // the challenge this page sent was accepted
      return;
    }
    loadGames().catch(() => {});
  });
  scope.onLive("game", ({ state, move }) => {
    const card = cards.get(state.id);
    if (!card) return;
    if (state.status !== 0) loadGames().catch(() => {}); // it finished: off this list
    else card.update(state, move);
  });
  scope.onLive("resync", () => {
    loadGames().catch(() => {});
    loadChallenges().catch(() => {});
  });
  scope.poll(() => {
    loadGames().catch(() => {});
    loadChallenges().catch(() => {});
  }, 15000);

  await Promise.all([loadGames(), loadChallenges()]);
}
