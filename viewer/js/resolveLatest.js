// viewer/js/resolveLatest.js
// ES module that exports a resolver for the "latest" outputs pointer.
// Usage:
//   import { resolveLatestPath } from '/viewer/js/resolveLatest.js';
//   const latestDir = await resolveLatestPath('/outputs');

const DEFAULT_TIMEOUT_MS = 2000;

async function _fetchWithTimeout(resource, options = {}, timeout = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const resp = await fetch(resource, { signal: controller.signal, ...options });
    return resp;
  } finally {
    clearTimeout(id);
  }
}

/**
 * Resolve the folder to use for "latest" outputs.
 * Returns either "latest" (if a real latest/ folder or symlink exists),
 * or the folder name read from latest.txt, or "latest" as a final fallback.
 *
 * baseOutputsUrl: URL path that serves outputs, e.g. "/outputs" or "http://127.0.0.1:8000/outputs"
 * timeoutMs: per-request timeout in milliseconds
 */
export async function resolveLatestPath(baseOutputsUrl, timeoutMs = DEFAULT_TIMEOUT_MS) {
  if (!baseOutputsUrl) return "latest";
  // normalize base (no trailing slash)
  const base = baseOutputsUrl.replace(/\/+$/, "");

  // 1) Fast path: HEAD the folder /latest/
  try {
    const headUrl = `${base}/latest/`;
    const head = await _fetchWithTimeout(headUrl, { method: "HEAD", cache: "no-store" }, timeoutMs);
    if (head && (head.ok || head.status === 200 || head.status === 304)) {
      return "latest";
    }
  } catch (e) {
    // network error or abort: ignore and try pointer file
  }

  // 2) Fallback: read latest.txt
  try {
    const txtUrl = `${base}/latest.txt`;
    const resp = await _fetchWithTimeout(txtUrl, { method: "GET", cache: "no-store" }, timeoutMs);
    if (resp && resp.ok) {
      const name = (await resp.text()).trim();
      if (name) return name;
    }
  } catch (e) {
    // ignore
  }

  // 3) Final fallback
  return "latest";
}
