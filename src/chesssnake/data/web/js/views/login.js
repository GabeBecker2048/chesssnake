// Log in, or create an account when the server allows it (api.registration = open).

import { post, setToken } from "../api.js";
import { h, replace } from "../ui.js";

export const NAV = "";

export function render(main, _params, ctx) {
  const open = ctx.info.registration === "open";
  let mode = "login";
  const box = h("div", { class: "card auth-box" });
  replace(main, box);
  draw();

  function draw() {
    const registering = mode === "register";
    const error = h("p", { class: "error", role: "alert" });
    const username = h("input", { name: "username", autocomplete: "username", required: true, autofocus: true });
    const password = h("input", {
      name: "password",
      type: "password",
      autocomplete: registering ? "new-password" : "current-password",
      required: true,
    });
    const confirm = registering
      ? h("input", { name: "confirm", type: "password", autocomplete: "new-password", required: true })
      : null;
    const submit = h("button", { type: "submit", class: "primary" }, registering ? "Create account" : "Log in");

    const form = h(
      "form",
      { class: "stack", onsubmit: onSubmit },
      h("h1", {}, registering ? "Create an account" : "Log in"),
      h("label", {}, "Username", username),
      h("label", {}, "Password", password),
      confirm ? h("label", {}, "Password again", confirm) : null,
      error,
      submit,
      open
        ? h(
            "p",
            { class: "muted small" },
            registering ? "Already have an account? " : "New here? ",
            h(
              "button",
              { type: "button", class: "link", onclick: () => { mode = registering ? "login" : "register"; draw(); } },
              registering ? "Log in" : "Create an account",
            ),
          )
        : h("p", { class: "muted small" }, "Accounts are made by an administrator of this server."),
    );
    replace(box, form);
    username.focus();

    async function onSubmit(ev) {
      ev.preventDefault();
      error.textContent = "";
      if (confirm && confirm.value !== password.value) {
        error.textContent = "The passwords do not match";
        return;
      }
      submit.disabled = true;
      try {
        const result = await post(registering ? "/auth/register" : "/auth/login", {
          username: username.value.trim(),
          password: password.value,
        });
        setToken(result.token);
        ctx.signedIn(result.user);
      } catch (err) {
        error.textContent = err.message;
        submit.disabled = false;
      }
    }
  }
}
