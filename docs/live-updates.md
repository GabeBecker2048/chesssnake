---
title: Live updates
---

Every board shows a move the moment it is made: in the browser, in
`chesssnake play`, and in your own clients.

Live updates are **on by default** and need no setup: they use the same address
and port as the rest of the server.

To check, open the web UI: the dot beside your name is green. Or:

```sh
curl http://localhost:8000/v1/info       # ... "websocket": true
```

## Behind a reverse proxy

The proxy must pass websocket connections through to `/v1/ws`.

- **Caddy:** `reverse_proxy` does it with no extra configuration.
- **nginx:** add these to the `location` block, with a read timeout longer than
  20 seconds:

  ```nginx
  proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 60s;
  ```

## Turning them off

```toml
[websocket]
enabled = false
```

or `CHESSSNAKE__WEBSOCKET__ENABLED=0`. Everything still works: clients check
the server every few seconds instead.

## Things to know

- **One server process.** Live updates only reach clients connected to the
  process that saved the move. Run a single process, as the Docker image does:
  no `uvicorn --workers`, no replicas behind a load balancer.
- **Limits.** By default 1000 connections in total and 10 per user. An idle
  connection costs about 56 KiB of memory.
- **Browsers on another site.** If a web page served from a different address
  connects to your server, list that address in `websocket.allowed_origins`.
  The built-in web UI needs nothing.

Every limit and timeout is in [Configuration](configuration.html#websocket). To
write a client that listens for updates, see [Websocket API](websocket-api.html).
