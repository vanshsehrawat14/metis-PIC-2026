/**
 * API origin for fetches.
 * - Default (dev, or unset): `/api`, proxied to FastAPI by vite.config.js.
 * - Set VITE_API_URL to a full origin (e.g. http://localhost:8000) to call the
 *   backend directly instead of through the proxy.
 */
export function getApiBaseUrl() {
  const u = import.meta.env.VITE_API_URL;
  if (typeof u === "string" && u.trim()) {
    return u.trim().replace(/\/$/, "");
  }
  return "/api";
}

/** Full URL for a path like `/health` or `/simulate`. */
export function apiUrl(path) {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${p}`;
}
