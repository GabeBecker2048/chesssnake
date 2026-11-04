// Your account: preferences, linked accounts, password, logins and api tokens,
// and logging out.

import { del, get, post } from "../api.js";
import { setting, updateSettings } from "../settings.js";
import { markColoursCard } from "./marks.js";
import { confirmAction, formatDate, h, replace, revealSecret, showError, toast } from "../ui.js";

export const NAV = "account";

export async function render(main, _params, ctx) {
  const tokens = h("div", { class: "table-wrap" });
  const linked = h("div", { class: "rows" });

  replace(
    main,
    h(
      "div",
      { class: "columns" },
      h(
        "section",
        {},
        markColoursCard(),
        h(
          "div",
          { class: "card" },
          h("h2", {}, "Logins and api tokens"),
          h("p", { class: "muted small" }, "Each browser or chesssnake login is a login; api tokens are for scripts and bots. Revoking one logs it out at once."),
          tokens,
        ),
        tokenForm(),
      ),
      h(
        "aside",
        {},
        preferences(),
        h(
          "div",
          { class: "card" },
          h("h2", {}, "Linked accounts"),
          h("p", { class: "muted small" }, "Other accounts that are you, such as Discord: a bot that knows one plays as you. An administrator links them (or a bot's /link command); you can unlink any here."),
          linked,
        ),
        passwordForm(),
        h(
          "div",
          { class: "card" },
          h("h2", {}, "Log out"),
          h("p", { class: "muted small" }, `Logged in as ${ctx.me.username}.`),
          h("button", { onclick: logout }, "Log out"),
        ),
      ),
    ),
  );

  async function logout() {
    try {
      await post("/auth/logout");
    } catch {
      // gone already: logging out locally is what matters
    }
    ctx.signOut();
  }

  function preferences() {
    const autoQueen = h("input", {
      type: "checkbox",
      name: "auto_queen",
      checked: Boolean(setting("auto_queen")),
      onchange: async () => {
        const wanted = autoQueen.checked;
        autoQueen.disabled = true;
        try {
          await updateSettings({ auto_queen: wanted });
          toast(wanted ? "Pawns now promote to a queen automatically" : "You will choose each promotion");
        } catch (err) {
          autoQueen.checked = !wanted; // not saved: show what is really in force
          showError(err);
        } finally {
          autoQueen.disabled = false;
        }
      },
    });
    return h(
      "div",
      { class: "card" },
      h("h2", {}, "Preferences"),
      h(
        "label",
        { class: "check" },
        autoQueen,
        h("span", {}, h("strong", {}, "Auto-queen"), h("span", { class: "muted small" }, "Promote pawns to a queen without asking. Off: you pick the piece.")),
      ),
      h("p", { class: "muted small" }, "Saved to your account, so it applies in every browser."),
    );
  }

  async function loadLinked() {
    const me = await get("/auth/me");
    replace(linked);
    if (!me.identities.length) linked.append(h("p", { class: "muted small" }, "None."));
    for (const identity of me.identities) {
      const label = `${identity.provider}: ${identity.external_id}`;
      linked.append(
        h(
          "div",
          { class: "row" },
          h("span", { class: "grow identity" }, label),
          h("button", { class: "small danger", onclick: async () => {
            if (!(await confirmAction(`Unlink ${label}?`, "A bot that knows this account will no longer play as you. Only an administrator can link it again.", "Unlink"))) return;
            try {
              await del(`/users/${ctx.me.id}/identities/${encodeURIComponent(identity.provider)}/${encodeURIComponent(identity.external_id)}`);
              toast(`Unlinked ${label}`);
            } catch (err) {
              showError(err);
            }
            loadLinked();
          } }, "Unlink"),
        ),
      );
    }
  }

  async function loadTokens() {
    const list = (await get("/auth/tokens")).tokens;
    const rows = list.map((t) =>
      h(
        "tr",
        {},
        h("td", {}, t.kind === "api" ? t.name || "(unnamed)" : "Login"),
        h("td", {}, t.kind),
        h("td", {}, formatDate(t.created_at)),
        h("td", {}, t.expires_at ? formatDate(t.expires_at) : "never"),
        h(
          "td",
          {},
          h("button", { class: "small danger", onclick: async () => {
            if (!(await confirmAction("Revoke this token?", "Anything using it is logged out at once. If it is this browser's login, you will be too.", "Revoke"))) return;
            try {
              await del(`/auth/tokens/${t.id}`);
              toast("Revoked");
              loadTokens();
            } catch (err) {
              showError(err);
            }
          } }, "Revoke"),
        ),
      ),
    );
    replace(
      tokens,
      h(
        "table",
        { class: "list" },
        h("thead", {}, h("tr", {}, ["Name", "Kind", "Created", "Expires", ""].map((x) => h("th", {}, x)))),
        h("tbody", {}, rows),
      ),
    );
  }

  function passwordForm() {
    const current = h("input", { type: "password", autocomplete: "current-password", required: true });
    const next = h("input", { type: "password", autocomplete: "new-password", required: true });
    const again = h("input", { type: "password", autocomplete: "new-password", required: true });
    const error = h("p", { class: "error", role: "alert" });
    return h(
      "form",
      { class: "card stack", onsubmit: async (ev) => {
        ev.preventDefault();
        error.textContent = "";
        if (next.value !== again.value) {
          error.textContent = "The new passwords do not match";
          return;
        }
        try {
          await post("/auth/password", { current_password: current.value, new_password: next.value });
          ev.target.reset();
          toast("Password changed. Your other logins were logged out; api tokens still work.");
          loadTokens();
        } catch (err) {
          error.textContent = err.message;
        }
      } },
      h("h2", {}, "Change password"),
      h("label", {}, "Current password", current),
      h("label", {}, "New password", next),
      h("label", {}, "New password again", again),
      error,
      h("button", { type: "submit", class: "primary" }, "Change password"),
    );
  }

  function tokenForm() {
    const name = h("input", { required: true, maxlength: "64", placeholder: "my-bot" });
    const days = h("input", { type: "number", min: "1", max: "3650", placeholder: "never" });
    const password = h("input", { type: "password", autocomplete: "current-password", required: true });
    const error = h("p", { class: "error", role: "alert" });
    return h(
      "form",
      { class: "card stack", onsubmit: async (ev) => {
        ev.preventDefault();
        error.textContent = "";
        try {
          const result = await post("/auth/tokens", {
            name: name.value.trim(),
            current_password: password.value,
            expires_in_days: days.value ? Number(days.value) : null,
          });
          ev.target.reset();
          revealSecret("Your new api token", "Copy it now: it is not shown again. Send it as Authorization: Bearer.", result.token);
          loadTokens();
        } catch (err) {
          error.textContent = err.message;
        }
      } },
      h("h2", {}, "New api token"),
      h("div", { class: "inline-form" }, h("label", {}, "Name", name), h("label", {}, "Expires after (days)", days)),
      h("label", {}, "Your password", password),
      error,
      h("button", { type: "submit", class: "primary" }, "Create token"),
    );
  }

  await Promise.all([loadTokens(), loadLinked()]);
}
