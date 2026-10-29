export function uniqueDocIds(hits) {
  const seen = new Set();
  const result = [];
  for (const hit of hits) {
    const id = hit.docId || hit.id;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    result.push(id);
  }
  return result;
}

export function recallAtK(hits, relevant, k = 5) {
  const labels = new Set(Object.keys(relevant || {}));
  if (labels.size === 0) return 0;
  const docs = uniqueDocIds(hits).slice(0, k);
  let hitCount = 0;
  for (const id of docs) if (labels.has(id)) hitCount += 1;
  return hitCount / labels.size;
}

export function ndcgAtK(hits, relevant, k = 5) {
  const docs = uniqueDocIds(hits).slice(0, k);
  let dcg = 0;
  docs.forEach((id, index) => {
    const rel = Number(relevant?.[id] || 0);
    if (rel > 0) dcg += (2 ** rel - 1) / Math.log2(index + 2);
  });
  const ideal = Object.values(relevant || {})
    .map(Number)
    .filter((value) => value > 0)
    .sort((a, b) => b - a)
    .slice(0, k);
  let idcg = 0;
  ideal.forEach((rel, index) => {
    idcg += (2 ** rel - 1) / Math.log2(index + 2);
  });
  return idcg > 0 ? dcg / idcg : 0;
}

export function mrrAtK(hits, relevant, k = 10) {
  const docs = uniqueDocIds(hits).slice(0, k);
  for (let i = 0; i < docs.length; i += 1) {
    if (Number(relevant?.[docs[i]] || 0) > 0) return 1 / (i + 1);
  }
  return 0;
}

export function median(values) {
  const list = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!list.length) return 0;
  const mid = Math.floor(list.length / 2);
  return list.length % 2 ? list[mid] : (list[mid - 1] + list[mid]) / 2;
}

export function percentile(values, p = 0.95) {
  const list = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!list.length) return 0;
  const index = Math.min(list.length - 1, Math.max(0, Math.ceil(p * list.length) - 1));
  return list[index];
}

export function round(value, digits = 3) {
  const factor = 10 ** digits;
  return Math.round(Number(value) * factor) / factor;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function highlight(text, query) {
  const safe = escapeHtml(text);
  const terms = String(query || "")
    .split(/\s+/)
    .map((term) => term.trim())
    .filter((term) => term.length >= 2)
    .slice(0, 6);
  if (!terms.length) return safe;
  let result = safe;
  for (const term of terms) {
    const escaped = escapeHtml(term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    result = result.replace(new RegExp(escaped, "gi"), (match) => `<mark>${match}</mark>`);
  }
  return result;
}

export function formatMs(value) {
  if (!Number.isFinite(value)) return "—";
  if (value < 1) return `${Math.round(value * 1000)} μs`;
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
