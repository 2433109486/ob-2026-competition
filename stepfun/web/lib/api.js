async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const error = new Error(body?.error || `${response.status} ${response.statusText}`);
    error.status = response.status;
    error.detail = body?.detail;
    error.hint = body?.hint;
    throw error;
  }
  return body;
}

export const api = {
  health: () => request("/api/health", { cache: "no-store" }),
  config: () => request("/api/config", { cache: "no-store" }),
  collections: () => request("/api/collections", { cache: "no-store" }),
  collection: (name) => request(`/api/collections/${encodeURIComponent(name)}`, { cache: "no-store" }),
  createCollection: (payload) =>
    request("/api/collections", { method: "POST", body: JSON.stringify(payload) }),
  deleteCollection: (name) =>
    request(`/api/collections/${encodeURIComponent(name)}`, { method: "DELETE" }),
  clearCollection: (name) =>
    request(`/api/collections/${encodeURIComponent(name)}/clear`, { method: "POST" }),
  documents: (name, limit = 200) =>
    request(
      `/api/documents?collection=${encodeURIComponent(name)}&limit=${encodeURIComponent(limit)}`,
      { cache: "no-store" },
    ),
  importDocuments: (payload) =>
    request("/api/import", { method: "POST", body: JSON.stringify(payload) }),
  search: (payload) =>
    request("/api/search", { method: "POST", body: JSON.stringify(payload) }),
};
