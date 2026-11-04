// Per-user settings, kept on the server (GET / PATCH /v1/auth/settings), so
// they follow the user to every browser. Loaded when the user logs in; the
// Account page changes them. The server only stores them: what they mean is up
// to this page (auto_queen: the board sends the queen without the picker).

import { get, patch } from "./api.js";

const DEFAULTS = { auto_queen: false };
let current = { ...DEFAULTS };

/** Fetch the logged-in user's settings. On failure the defaults stay in force. */
export async function loadSettings() {
  try {
    current = { ...DEFAULTS, ...(await get("/auth/settings")) };
  } catch {
    current = { ...DEFAULTS };
  }
  return current;
}

/** One setting's current value. Read at the moment it matters, so a change applies at once. */
export function setting(name) {
  return current[name];
}

/** Save some settings; resolves to them all. Rejects (and changes nothing) if the server refuses. */
export async function updateSettings(changes) {
  current = { ...DEFAULTS, ...(await patch("/auth/settings", changes)) };
  return current;
}

/** Forget them (logout). */
export function clearSettings() {
  current = { ...DEFAULTS };
}
