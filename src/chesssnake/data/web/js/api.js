// The REST client. Every call goes to /v1 with the session token as a bearer
// token, exactly as `chesssnake play` sends it.

const TOKEN_KEY = "chesssnake.token";

export class ApiError extends Error {
  constructor(status, type, message) {
    super(message);
    this.status = status;
    this.type = type; // the server's error_type, e.g. "VersionConflictError"
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Storage blocked (a private window): the login lasts until the page closes.
  }
  memoryToken = token;
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // nothing stored
  }
  memoryToken = null;
}

let memoryToken = getToken();

export function token() {
  return memoryToken;
}

/** Fired on window when a request finds the login gone (401): the app shows the login page. */
export const LOGGED_OUT = "chesssnake:logged-out";

function describe(body, status) {
  if (body && typeof body.detail === "string") return body.detail;
  // FastAPI's own validation errors: {"detail": [{"loc": [...], "msg": "..."}]}
  if (body && Array.isArray(body.detail) && body.detail.length) {
    const first = body.detail[0];
    const where = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body" && p !== "query").join(".") : "";
    return where ? `${where}: ${first.msg}` : first.msg;
  }
  return `Request failed (HTTP ${status})`;
}

/**
 * Call the API. Resolves to the decoded JSON (or text when asText), null for 204.
 * Rejects with an ApiError carrying the server's error_type and detail.
 */
export async function api(method, path, body = undefined, { asText = false, query = null } = {}) {
  const headers = {};
  const sent = memoryToken;
  if (sent) headers.Authorization = `Bearer ${sent}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let url = `/v1${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== null && v !== undefined && v !== "") params.set(k, v);
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }
  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "NetworkError", "Cannot reach the server");
  }
  if (response.status === 204) return null;
  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch {
      // not JSON (a proxy's error page)
    }
    const error = new ApiError(response.status, data?.error_type || "", describe(data, response.status));
    if (response.status === 401 && sent && sent === memoryToken) {
      clearToken();
      window.dispatchEvent(new CustomEvent(LOGGED_OUT, { detail: error.message }));
    }
    throw error;
  }
  return asText ? response.text() : response.json();
}

export const get = (path, query) => api("GET", path, undefined, { query });
export const post = (path, body = {}) => api("POST", path, body);
export const patch = (path, body) => api("PATCH", path, body);
export const del = (path) => api("DELETE", path);
