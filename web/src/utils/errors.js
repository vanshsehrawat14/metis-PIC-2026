/**
 * Map low-level browser/fetch errors to user-facing text + fix hints.
 * Pass an Error, or a string (message text).
 */
export function userFacingMessage(maybe) {
  const msg = maybe instanceof Error ? maybe.message : String(maybe ?? "");
  if (/timed out|timeout/i.test(msg)) {
    return (
      "API request timed out. The backend may still be starting the simulation " +
      "engine (it initializes asynchronously after boot). Confirm the API responds " +
      "at /health, then retry."
    );
  }
  if (/Failed to fetch|Load failed|NetworkError|Network request failed/i.test(msg)) {
    return (
      "Browser could not reach the API. Start the backend " +
      "(uvicorn api.main:app --port 8000) and confirm VITE_API_URL / the /api proxy " +
      "points at it."
    );
  }
  if (/HTML instead of JSON|unexpected content type|Unexpected token </i.test(msg)) {
    return (
      "The frontend got HTML instead of JSON — /api/* is hitting the SPA, not the " +
      "backend. Check the Vite proxy in vite.config.js (or VITE_API_URL) points at " +
      "the FastAPI server."
    );
  }
  return msg;
}

/** Avoid raw fetch error strings in the scrolling ticker. */
export function sanitizeForTicker(text) {
  if (text == null) {
    return "";
  }
  const s = String(text);
  if (/failed to fetch|load failed|networkerror|network request failed/i.test(s)) {
    return "API unavailable";
  }
  return s;
}
