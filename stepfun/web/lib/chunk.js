export const TEXT_EXTENSIONS = [".txt", ".md", ".markdown", ".json", ".csv"];

export function hashString(value) {
  let hash = 0x811c9dc5;
  const text = String(value);
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function normalizeText(text) {
  return String(text || "")
    .replace(/\r\n?/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function splitSentences(paragraph) {
  const parts = paragraph
    .split(/(?<=[。！？!?；;])/)
    .map((part) => part.trim())
    .filter(Boolean);
  return parts.length ? parts : [paragraph];
}

/**
 * Chunk Chinese/English notes by paragraph and sentence boundaries.
 * Defaults: 440 chars, 80 chars overlap, which keeps each chunk within the
 * 512-token limit of bge-small-zh for typical Chinese text.
 */
export function chunkText(text, { maxChars = 440, overlap = 80 } = {}) {
  const normalized = normalizeText(text);
  if (!normalized) return [];
  const paragraphs = normalized.split(/\n\s*\n/).filter((p) => p.trim());
  const chunks = [];
  let current = "";

  const flush = () => {
    const value = current.trim();
    if (value) chunks.push(value);
    current = "";
  };

  const append = (piece) => {
    const value = String(piece || "").trim();
    if (!value) return;
    if (!current) {
      current = value;
      return;
    }
    if (current.length + value.length + 1 <= maxChars) {
      current += `${/[。！？!?；;：:]$/.test(current) ? "" : " "}${value}`;
      return;
    }
    const tail = current.slice(-overlap);
    flush();
    current = `${tail}${tail && !/[\s。！？!?；;：:]$/.test(tail) ? " " : ""}${value}`;
    if (current.length > maxChars * 1.4) {
      // A single very long sentence: hard split, preserving overlap.
      const long = current;
      current = "";
      for (let start = 0; start < long.length; start += maxChars - overlap) {
        chunks.push(long.slice(start, start + maxChars));
      }
    }
  };

  for (const paragraph of paragraphs) {
    if (paragraph.length <= maxChars) {
      append(paragraph);
      continue;
    }
    for (const sentence of splitSentences(paragraph)) {
      if (sentence.length > maxChars) {
        append(sentence.slice(0, maxChars));
        let start = maxChars - overlap;
        while (start < sentence.length) {
          append(sentence.slice(start, start + maxChars));
          start += maxChars - overlap;
        }
      } else {
        append(sentence);
      }
    }
  }
  flush();
  return chunks.filter((chunk, index, all) => chunk.length >= 2 && all.indexOf(chunk) === index);
}

export function extractTitle(text, fallback = "未命名文档") {
  const normalized = normalizeText(text);
  const heading = normalized.match(/^\s*#{1,3}\s+(.+)$/m);
  if (heading?.[1]) return heading[1].trim().slice(0, 120);
  const firstLine = normalized.split("\n").find((line) => line.trim().length > 0);
  if (firstLine && firstLine.trim().length <= 80) return firstLine.trim();
  return fallback;
}

export function stripMarkdownHeading(text) {
  return normalizeText(text).replace(/^\s*#{1,3}\s+.+\n+/, "");
}

export function fileDocId(file) {
  return `file-${hashString(`${file.name}:${file.size}:${file.lastModified}`)}`;
}

export function chunkId(docId, index) {
  return `${docId}#${String(index).padStart(3, "0")}`.slice(0, 200);
}

export function makeChunks(doc, options = {}) {
  const id = String(doc.id || doc.docId || `doc-${hashString(doc.text)}`).slice(0, 120);
  const title = String(doc.title || extractTitle(doc.text)).slice(0, 280);
  const text = stripMarkdownHeading(doc.text);
  const parts = chunkText(text, options);
  return parts.map((part, index) => ({
    id: chunkId(id, index),
    docId: id,
    title,
    text: part,
    chunkIndex: index,
    source: String(doc.source || "").slice(0, 480),
    tags: Array.isArray(doc.tags) ? doc.tags.slice(0, 10) : [],
  }));
}

export async function parseFiles(fileList) {
  const files = [...(fileList || [])];
  const docs = [];
  for (const file of files) {
    const lower = file.name.toLowerCase();
    if (!TEXT_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
      throw new Error(`暂不支持 ${file.name}，请导入 .txt / .md / .json / .csv 文本文件`);
    }
    const raw = await file.text();
    if (!raw.trim()) continue;
    if (lower.endsWith(".json")) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          for (const item of parsed) {
            if (typeof item === "string") {
              docs.push({
                id: `json-${hashString(`${file.name}:${item}`)}`,
                title: extractTitle(item, file.name.replace(/\.json$/i, "")),
                source: file.name,
                tags: [],
                text: item,
              });
            } else if (item && typeof item.text === "string") {
              docs.push({
                id: String(item.id || `json-${hashString(`${file.name}:${item.text}`)}`),
                title: String(item.title || extractTitle(item.text, file.name)),
                source: String(item.source || file.name),
                tags: Array.isArray(item.tags) ? item.tags : [],
                text: item.text,
              });
            }
          }
          continue;
        }
      } catch {
        // Fall through and treat invalid JSON as plain text.
      }
    }
    docs.push({
      id: fileDocId(file),
      title: extractTitle(raw, file.name.replace(/\.[^.]+$/, "")),
      source: file.name,
      tags: [],
      text: raw,
    });
  }
  return docs;
}
