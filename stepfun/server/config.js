import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(here, "..");
export const WEB_DIR = path.join(ROOT, "web");
export const DATA_DIR = path.join(ROOT, "data");
export const RUNTIME_DIR = path.join(ROOT, "runtime");

// Load .env without an extra dependency. Existing environment variables win.
try {
  const envFile = path.join(ROOT, ".env");
  if (fs.existsSync(envFile)) {
    for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/)) {
      const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (!match || match[1].startsWith("#")) continue;
      let value = match[2];
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (process.env[match[1]] === undefined) process.env[match[1]] = value;
    }
  }
} catch {
  // A malformed .env must not prevent the app from starting.
}

const int = (value, fallback) => {
  const n = Number.parseInt(value ?? "", 10);
  return Number.isFinite(n) ? n : fallback;
};

export const config = {
  port: int(process.env.PORT, 5173),
  host: process.env.HOST || "127.0.0.1",

  seekdb: {
    host: process.env.SEEKDB_HOST || "127.0.0.1",
    port: int(process.env.SEEKDB_PORT, 2881),
    user: process.env.SEEKDB_USER || "root",
    password: process.env.SEEKDB_PASSWORD || "",
    database: process.env.SEEKDB_DATABASE || "stepfun_kb",
    // Embedded mode is supported on Linux/macOS. On Windows use a local
    // seekdb server (server mode); embedded mode is not supported there.
    path: process.env.SEEKDB_PATH || "",
    mode: process.env.SEEKDB_MODE || "auto",
  },

  model: {
    id: process.env.MODEL_ID || "bge-small-zh-v1.5",
    source:
      "Xenova/bge-small-zh-v1.5 (ONNX conversion of BAAI/bge-small-zh-v1.5)",
    revision: "75c43b069aac4d136ba6bc1122f995fedcfd2781",
    dimension: int(process.env.MODEL_DIM, 512),
    dtype: process.env.MODEL_DTYPE || "q8",
    queryPrefix:
      process.env.QUERY_PREFIX ||
      "为这个句子生成表示以用于检索相关文章：",
  },

  collection: {
    defaultName: process.env.DEFAULT_COLLECTION || "default",
    hnsw: {
      m: int(process.env.HNSW_M, 16),
      efConstruction: int(process.env.HNSW_EF_CONSTRUCTION, 200),
      efSearch: int(process.env.HNSW_EF_SEARCH, 64),
    },
    fulltext: {
      analyzer: process.env.FULLTEXT_ANALYZER || "ngram2",
      minNgram: int(process.env.FULLTEXT_MIN_NGRAM, 2),
      maxNgram: int(process.env.FULLTEXT_MAX_NGRAM, 2),
    },
  },

  limits: {
    maxDocumentsPerImport: int(process.env.MAX_DOCS_PER_IMPORT, 2000),
    maxTextChars: int(process.env.MAX_TEXT_CHARS, 20000),
    maxTopK: int(process.env.MAX_TOP_K, 50),
  },
};
