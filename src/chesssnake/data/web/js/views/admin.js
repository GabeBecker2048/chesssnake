// The admin panel: accounts, games, and what the server is running. Every
// action is an ordinary admin-only API call; the server checks the role on each
// one, so this page only decides what to show.

import { del, get, patch, post } from "../api.js";
import { live } from "../live.js";
import { confirmAction, dialog, formatDate, h, replace, resultToken, showError, timeAgo, toast, userLink } from "../ui.js";

export const NAV = "admin";

const PAGE = 50;

export async function render(main, _params, ctx) {
  if (ctx.me.role !== "admin") {
    replace(main, h("div", { class: "card" }, h("h1", {}, "Administrators only"), h("a", { href: "#/" }, "Back to Play")));
    return;
  }
  const panel = h("div", {});
  const tabs = { Users: usersTab, Games: gamesTab, Server: serverTab };
  const tabBar = h(
    "div",
    { class: "tabs", role: "tablist" },
    Object.keys(tabs).map((name) => h("button", { role: "tab", dataset: { tab: name }, onclick: () => show(name) }, name)),
  );
  replace(main, h("h1", {}, "Admin"), tabBar, panel);

  async function show(name) {
    for (const b of tabBar.children) {
      b.classList.toggle("active", b.dataset.tab === name);
      b.setAttribute("aria-selected", String(b.dataset.tab === name));
    }
    replace(panel, h("p", { class: "muted loading" }, "Loading…"));
    try {
      await tabs[name](panel, ctx);
    } catch (err) {
      replace(panel, h("p", { class: "error" }, err.message));
    }
  }

  await show("Users");
}

// --- Users ---------------------------------------------------------------------

async function usersTab(panel, ctx) {
  const search = h("input", { type: "search", placeholder: "Search by name", "aria-label": "Search users" });
  const body = h("tbody", {});
  const more = h("button", { class: "small", hidden: true, onclick: () => load(false) }, "Show more");
  let offset = 0;

  replace(
    panel,
    createUserForm(() => load(true)),
    h(
      "div",
      { class: "card" },
      h("div", { class: "inline-form" }, h("label", {}, "Users", search)),
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "list" },
          h("thead", {}, h("tr", {}, ["User", "Role", "Status", "Linked ids", "Joined", ""].map((x) => h("th", {}, x)))),
          body,
        ),
      ),
      more,
    ),
  );

  let timer = null;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => load(true), 200);
  });

  async function load(fresh) {
    if (fresh) {
      offset = 0;
      replace(body);
    }
    const { users } = await get("/users/search", { q: search.value.trim(), limit: PAGE, offset });
    offset += users.length;
    for (const user of users) body.append(userRow(user));
    more.hidden = users.length < PAGE;
  }

  function userRow(user) {
    const row = h("tr", {});
    const tokensRow = h("tr", { hidden: true }, h("td", { colspan: "6" }));
    draw(user);
    const frag = document.createDocumentFragment();
    frag.append(row, tokensRow);
    return frag;

    function draw(u) {
      user = u;
      const isMe = u.id === ctx.me.id;
      replace(
        row,
        h("td", {}, userLink(u.username), h("span", { class: "muted small" }, ` #${u.id}`)),
        h("td", {}, u.role === "admin" ? h("span", { class: "badge" }, "admin") : "user"),
        h("td", {}, u.disabled_at ? h("span", { class: "badge danger" }, "disabled") : "active", u.has_password ? "" : h("span", { class: "muted small" }, " · no password")),
        h("td", { class: "small" }, u.identities.map((i) => `${i.provider}:${i.external_id}`).join(", ") || h("span", { class: "muted" }, "none")),
        h("td", { class: "small" }, formatDate(u.created_at)),
        h(
          "td",
          {},
          h(
            "div",
            { class: "button-row" },
            h("button", { class: "small", onclick: () => change({ role: u.role === "admin" ? "user" : "admin" }) }, u.role === "admin" ? "Make user" : "Make admin"),
            h("button", { class: `small${u.disabled_at ? "" : " danger"}`, disabled: isMe, title: isMe ? "You cannot disable yourself" : null, onclick: toggleDisabled }, u.disabled_at ? "Enable" : "Disable"),
            h("button", { class: "small", onclick: resetPassword }, "Reset password"),
            h("button", { class: "small", onclick: rename }, "Rename"),
            h("button", { class: "small", onclick: toggleTokens }, "Tokens"),
          ),
        ),
      );
    }

    async function change(body, message = "Saved") {
      try {
        draw(await patch(`/users/${user.id}`, body));
        toast(message);
      } catch (err) {
        showError(err);
      }
    }

    async function toggleDisabled() {
      if (user.disabled_at) return change({ disabled: false }, "Enabled");
      if (await confirmAction(`Disable ${user.username}?`, "They are logged out everywhere at once and cannot log in until enabled again.", "Disable")) {
        change({ disabled: true }, "Disabled");
      }
    }

    async function resetPassword() {
      const values = await dialog({
        title: `Reset ${user.username}'s password`,
        text: "Every login and api token they have is revoked.",
        fields: [{ name: "password", label: "New password", type: "password", autocomplete: "new-password" }],
        submit: "Reset",
        danger: true,
      });
      if (values) change({ password: values.password }, "Password reset");
    }

    async function rename() {
      const values = await dialog({ title: `Rename ${user.username}`, fields: [{ name: "username", label: "New username", value: user.username }], submit: "Rename" });
      if (values && values.username.trim() !== user.username) change({ username: values.username.trim() }, "Renamed");
    }

    async function toggleTokens() {
      if (!tokensRow.hidden) {
        tokensRow.hidden = true;
        return;
      }
      tokensRow.hidden = false;
      const cell = tokensRow.firstChild;
      replace(cell, h("span", { class: "muted" }, "Loading…"));
      try {
        const { tokens } = await get("/auth/tokens", { user_id: user.id });
        replace(
          cell,
          tokens.length
            ? h(
                "div",
                { class: "rows" },
                tokens.map((t) => {
                  const line = h(
                    "div",
                    { class: "row" },
                    h("span", { class: "grow small" }, `${t.kind === "api" ? t.name : "login"} · created ${formatDate(t.created_at)} · expires ${t.expires_at ? formatDate(t.expires_at) : "never"}`),
                    h("button", { class: "small danger", onclick: async () => {
                      try {
                        await del(`/auth/tokens/${t.id}`);
                        line.remove();
                        toast("Revoked");
                      } catch (err) {
                        showError(err);
                      }
                    } }, "Revoke"),
                  );
                  return line;
                }),
              )
            : h("span", { class: "muted small" }, "No logins or tokens."),
        );
      } catch (err) {
        replace(cell, h("span", { class: "error" }, err.message));
      }
    }
  }

  await load(true);
}

function createUserForm(onCreated) {
  const username = h("input", { required: true, autocomplete: "off" });
  const password = h("input", { type: "password", autocomplete: "new-password", placeholder: "none: api tokens only" });
  const role = h("select", {}, h("option", { value: "user" }, "user"), h("option", { value: "admin" }, "admin"));
  const error = h("p", { class: "error", role: "alert" });
  return h(
    "form",
    { class: "card stack", onsubmit: async (ev) => {
      ev.preventDefault();
      error.textContent = "";
      try {
        const user = await post("/users", { username: username.value.trim(), password: password.value || null, role: role.value });
        ev.target.reset();
        toast(`Created ${user.username}`);
        onCreated();
      } catch (err) {
        error.textContent = err.message;
      }
    } },
    h("h2", {}, "Create a user"),
    h("div", { class: "inline-form" }, h("label", {}, "Username", username), h("label", {}, "Password", password), h("label", {}, "Role", role), h("button", { type: "submit", class: "primary" }, "Create")),
    error,
  );
}

// --- Games ---------------------------------------------------------------------

async function gamesTab(panel) {
  const liveBody = h("tbody", {});
  const finishedBody = h("tbody", {});
  const more = h("button", { class: "small", hidden: true, onclick: () => loadFinished() }, "Show more");
  let before = null;

  const table = (head, body) =>
    h("div", { class: "table-wrap" }, h("table", { class: "list" }, h("thead", {}, h("tr", {}, head.map((x) => h("th", {}, x)))), body));

  replace(
    panel,
    createGameForm(() => loadLive()),
    h("div", { class: "card" }, h("h2", {}, "In progress"), table(["Game", "White", "Black", "Group", "Last move", ""], liveBody)),
    h("div", { class: "card" }, h("h2", {}, "Finished"), table(["Game", "White", "Black", "Result", "Finished", ""], finishedBody), more),
  );

  function actions(g, onDeleted) {
    return h(
      "td",
      {},
      h(
        "div",
        { class: "button-row" },
        h("a", { class: "button small", href: `#/game/${g.id}` }, g.status === 0 ? "Watch" : "View"),
        h("button", { class: "small danger", onclick: async () => {
          if (!(await confirmAction(`Delete game ${g.id}?`, `${g.white_name} vs ${g.black_name}, and all its moves. This cannot be undone.`, "Delete"))) return;
          try {
            await del(`/games/${g.id}`);
            toast(`Deleted game ${g.id}`);
            onDeleted();
          } catch (err) {
            showError(err);
          }
        } }, "Delete"),
      ),
    );
  }

  async function loadLive() {
    const { games } = await get("/games/live", { limit: 200 });
    replace(liveBody);
    if (!games.length) liveBody.append(h("tr", {}, h("td", { colspan: "6", class: "muted" }, "None.")));
    for (const g of games) {
      const row = h(
        "tr",
        {},
        h("td", {}, `#${g.id}`),
        h("td", {}, userLink(g.white_name)),
        h("td", {}, userLink(g.black_name)),
        h("td", {}, String(g.group_id)),
        h("td", { class: "small" }, timeAgo(g.updated_at)),
      );
      row.append(actions(g, () => row.remove()));
      liveBody.append(row);
    }
  }

  async function loadFinished() {
    const { games } = await get("/games/finished", { limit: PAGE, before });
    if (before === null && !games.length) finishedBody.append(h("tr", {}, h("td", { colspan: "6", class: "muted" }, "None.")));
    for (const g of games) {
      const row = h(
        "tr",
        {},
        h("td", {}, `#${g.id}`),
        h("td", {}, userLink(g.white_name)),
        h("td", {}, userLink(g.black_name)),
        h("td", {}, resultToken(g)),
        h("td", { class: "small" }, formatDate(g.updated_at)),
      );
      row.append(actions(g, () => row.remove()));
      finishedBody.append(row);
    }
    if (games.length) before = games[games.length - 1].id;
    more.hidden = games.length < PAGE;
  }

  await Promise.all([loadLive(), loadFinished()]);
}

function createGameForm(onCreated) {
  const white = h("input", { required: true, autocomplete: "off" });
  const black = h("input", { required: true, autocomplete: "off" });
  const group = h("input", { type: "number", value: "0", required: true });
  const error = h("p", { class: "error", role: "alert" });
  return h(
    "form",
    { class: "card stack", onsubmit: async (ev) => {
      ev.preventDefault();
      error.textContent = "";
      try {
        const [w, b] = await Promise.all([get("/users", { username: white.value.trim() }), get("/users", { username: black.value.trim() })]);
        const state = await post("/games", { white_id: w.id, black_id: b.id, group_id: Number(group.value) });
        toast(`Game ${state.id}: ${state.white_name} vs ${state.black_name}`, { href: `#/game/${state.id}`, linkText: "Watch" });
        onCreated();
      } catch (err) {
        error.textContent = err.message;
      }
    } },
    h("h2", {}, "Start a game"),
    h("p", { class: "muted small" }, "Without a challenge. If these two already have a game in progress in the group, that game is returned instead."),
    h("div", { class: "inline-form" }, h("label", {}, "White", white), h("label", {}, "Black", black), h("label", {}, "Group", group), h("button", { type: "submit", class: "primary" }, "Start")),
    error,
  );
}

// --- Server ----------------------------------------------------------------------

async function serverTab(panel, ctx) {
  const info = await get("/info");
  const [{ games }, { users }] = await Promise.all([get("/games/live", { limit: 200 }), get("/users/search", { limit: 200 })]);
  const rows = [
    ["Version", info.version],
    ["Registration", info.registration === "open" ? "open: anyone can create an account" : "closed: administrators create accounts"],
    ["Live updates", info.websocket ? "on (websockets at /v1/ws)" : "off: clients poll"],
    ["This browser", live.isLive ? "connected live" : ctx.info.websocket ? "reconnecting" : "polling"],
    ["Games in progress", games.length >= 200 ? "200+" : String(games.length)],
    ["Users", users.length >= 200 ? "200+" : String(users.length)],
  ];
  replace(
    panel,
    h(
      "div",
      { class: "card" },
      h("table", { class: "list" }, h("tbody", {}, rows.map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, v))))),
      h("p", { class: "muted small" }, "Settings are changed in the server's config file or environment; see chesssnake config show."),
    ),
  );
}
