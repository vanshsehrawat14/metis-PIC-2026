import { apiUrl } from "./apiBase.js";

const DEFAULT_API_TIMEOUT_MS = 60000;

function isJsonContentType(contentType) {
  return /(^|;|\s)(application\/json|application\/[\w.+-]+\+json)(;|$)/i.test(
    contentType || "",
  );
}

function getApiTimeoutMs() {
  const raw = import.meta.env.VITE_API_TIMEOUT_MS;
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && parsed >= 1000) {
    return parsed;
  }
  return DEFAULT_API_TIMEOUT_MS;
}

export async function requestJson(method, path, body) {
  const controller = new AbortController();
  const timeoutMs = getApiTimeoutMs();
  const timerId = setTimeout(() => controller.abort(), timeoutMs);
  const options = {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    signal: controller.signal,
  };

  if (body !== undefined) {
    options.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(apiUrl(path), options);
    const contentType = response.headers.get("content-type") || "";

    if (!isJsonContentType(contentType)) {
      const bodyPreview = await response.text().catch(() => "");
      if (/<(!doctype|html)/i.test(bodyPreview)) {
        throw new Error(
          "API returned HTML instead of JSON. Check VITE_API_URL, proxy routing, or SPA rewrite rules.",
        );
      }
      throw new Error(
        `API returned unexpected content type: ${contentType || "unknown"}`,
      );
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(
        error.detail ||
          error.message ||
          error.error ||
          `API error ${response.status}`,
      );
    }

    return await response.json();
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`API request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw error;
  } finally {
    clearTimeout(timerId);
  }
}
