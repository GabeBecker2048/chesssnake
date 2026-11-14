---
title: Hosting publicly
---

On your own network the defaults are fine. Before the server is reachable from
the internet, go through this page.

## Checklist

- [ ] **HTTPS.** Passwords and tokens cross the network, so put the server
  behind a reverse proxy that serves HTTPS.
- [ ] **A strong admin password.** Anyone can reach the login page.
- [ ] **Registration closed**, unless you want strangers to sign up. It is
  closed by default.
- [ ] **A request limit at the proxy.** chesssnake does not limit login
  attempts itself. Each attempt is slow on purpose, but a public server
  should rate-limit `/v1/auth/login`.
- [ ] **API docs off**, if you do not want every route described to visitors:
  `api.docs = false`. They hold no data and need no login.
- [ ] **Backups.** See [Upgrading and backups](upgrading.html#backups).

## A reverse proxy

Proxy the whole site to the server. Nothing needs rewriting.

With Caddy, this is the entire configuration, HTTPS certificate included:

```
chess.example {
    reverse_proxy localhost:8000
}
```

With nginx, also pass websockets through if you use
[live updates](live-updates.html#behind-a-reverse-proxy).

When a proxy on the same machine is the only way in, keep the server itself
private by publishing the port on localhost only:

```yaml
    ports:
      - "127.0.0.1:8000:8000"
```

## What is public without a login

| Address | What it shows |
|---|---|
| `/` and `/assets/...` | the web UI's pages, which hold no data until you log in |
| `/health` | `{"status": "ok"}` |
| `/v1/info` | the version, and whether registration and live updates are on |
| `/docs`, `/redoc`, `/openapi.json` | the API's description (turn off with `api.docs = false`) |
| `/v1/auth/login`, `/v1/auth/register` | logging in, and registering when it is open |

Everything else needs a login. Any logged-in user can watch any game and see
any username, so only give accounts to people you are happy to have looking.

## Only bots, no website

To serve the API alone, turn the web UI off:

```toml
[web]
enabled = false
```

## How logins are kept safe

- Passwords are stored as Argon2id hashes, and tokens as hashes too: neither can
  be read back out of the database.
- A wrong username and a wrong password give the same answer.
- Logging out, a password reset or disabling an account takes effect at once.
- The web UI loads nothing from other sites and is served with a strict
  Content Security Policy.
- `chesssnake login` warns before sending a password over plain HTTP.
