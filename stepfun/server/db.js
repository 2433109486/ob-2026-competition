import {
  SeekdbAdminClient,
  SeekdbClient,
  Schema,
  FulltextIndexConfig,
  VectorIndexConfig,
} from "seekdb";
import { config } from "./config.js";

const COLLECTION_PREFIX = "kb_";
const DEFAULT_DISPLAY_NAME = "我的知识库";

const nowMs = () => Number(process.hrtime.bigint() / 1000n) / 1000;

function assert(condition, message) {
  if (!condition) {
    const error = new Error(message);
    error.statusCode = 400;
    throw error;
  }
}

function normalizeCollectionKey(input) {
  const raw = String(input || "").trim().toLowerCase();
  const key = raw.replace(/^kb_/, "").replace(/[^a-z0-9_-]/g, "");
  assert(/^[a-z0-9][a-z0-9_-]{0,47}$/.test(key), "集合名只能包含小写字母、数字、下划线和连字符");
  return key;
}

function tableCollectionName(key) {
  return `${COLLECTION_PREFIX}${key}`;
}

function displayNameFromKey(key) {
  return key === config.collection.defaultName ? DEFAULT_DISPLAY_NAME : key;
}

/**
 * Remove query-string operators that would be interpreted by seekdb's
 * DBMS_HYBRID_SEARCH query parser. The cleaned query is still the exact user
 * query semantically; only punctuation/operator characters are normalised.
 */
export function normalizeQueryText(input) {
  return String(input || "")
    .slice(0, 300)
    .replace(/[+\-=&|><!(){}[\]^"~*?:\\/]/g, " ")
    .replace(/[，。！？；：、（）【】《》“”‘’]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function toIso(value) {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString();
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toISOString();
}

export class KBStore {
  constructor() {
    this.client = null;
    this.admin = null;
    this.ready = false;
    this.initError = null;
    this.initPromise = null;
    this.mode = "server";
    this.backend = "seekdb-server";
    this.startedAt = new Date().toISOString();
  }

  async init() {
    if (this.ready) return this;
    if (this.initPromise) return this.initPromise;
    this.initPromise = (async () => {
      try {
        const mode =
          config.seekdb.mode === "embedded" ||
          (config.seekdb.mode === "auto" &&
            config.seekdb.path &&
            process.platform !== "win32")
            ? "embedded"
            : "server";

        if (mode === "embedded") {
          this.mode = "embedded";
          this.backend = "seekdb-embedded";
          const dbPath = config.seekdb.path || "runtime/seekdb-embedded";
          this.client = new SeekdbClient({
            path: dbPath,
            database: config.seekdb.database,
          });
        } else {
          this.mode = "server";
          this.backend = "seekdb-server";
          this.admin = new SeekdbAdminClient({
            host: config.seekdb.host,
            port: config.seekdb.port,
            user: config.seekdb.user,
            password: config.seekdb.password,
          });
          await this.admin.createDatabase(config.seekdb.database);
          await this.admin.close();
          this.admin = null;
          this.client = new SeekdbClient({
            host: config.seekdb.host,
            port: config.seekdb.port,
            user: config.seekdb.user,
            password: config.seekdb.password,
            database: config.seekdb.database,
          });
        }

        await this.client.execute("SELECT 1 AS ok");
        await this.ensureRelationalTables();
        await this.ensureDefaultCollection();
        this.ready = true;
        this.initError = null;
        return this;
      } catch (error) {
        this.ready = false;
        this.initError = error;
        this.initPromise = null;
        throw error;
      }
    })();
    return this.initPromise;
  }

  async close() {
    try {
      await this.client?.close();
    } catch {
      // ignore close errors
    }
  }

  schema() {
    return new Schema({
      fulltextIndex: new FulltextIndexConfig(config.collection.fulltext.analyzer, {
        min_ngram_size: config.collection.fulltext.minNgram,
        max_ngram_size: config.collection.fulltext.maxNgram,
      }),
      vectorIndex: new VectorIndexConfig({
        hnsw: {
          dimension: config.model.dimension,
          distance: "cosine",
          type: "hnsw",
          lib: "vsag",
          m: config.collection.hnsw.m,
          ef_construction: config.collection.hnsw.efConstruction,
          ef_search: config.collection.hnsw.efSearch,
        },
        embeddingFunction: null,
      }),
    });
  }

  async ensureRelationalTables() {
    await this.client.execute(`
      CREATE TABLE IF NOT EXISTS kb_collections (
        name VARCHAR(64) PRIMARY KEY,
        display_name VARCHAR(200) NOT NULL,
        model VARCHAR(128) NOT NULL,
        dimension INT NOT NULL,
        dtype VARCHAR(16) NOT NULL,
        doc_count INT DEFAULT 0,
        chunk_count INT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_import_at TIMESTAMP NULL,
        last_refresh_at TIMESTAMP NULL
      )
    `);
    await this.client.execute(`
      CREATE TABLE IF NOT EXISTS kb_documents (
        collection_name VARCHAR(64) NOT NULL,
        doc_id VARCHAR(128) NOT NULL,
        title VARCHAR(300) NOT NULL,
        source_name VARCHAR(500),
        tags JSON,
        chunk_count INT DEFAULT 0,
        imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (collection_name, doc_id)
      )
    `);
  }

  async ensureDefaultCollection() {
    const key = normalizeCollectionKey(config.collection.defaultName);
    if (!(await this.client.hasCollection(tableCollectionName(key)))) {
      await this.client.createCollection({
        name: tableCollectionName(key),
        schema: this.schema(),
      });
    }
    const rows = await this.client.execute(
      "SELECT name FROM kb_collections WHERE name = ?",
      [key],
    );
    if (!rows || rows.length === 0) {
      await this.client.execute(
        `INSERT INTO kb_collections
          (name, display_name, model, dimension, dtype, doc_count, chunk_count)
         VALUES (?, ?, ?, ?, ?, 0, 0)`,
        [
          key,
          displayNameFromKey(key),
          config.model.id,
          config.model.dimension,
          config.model.dtype,
        ],
      );
    }
  }

  async collection(key) {
    const normalized = normalizeCollectionKey(key);
    const name = tableCollectionName(normalized);
    if (!(await this.client.hasCollection(name))) {
      const error = new Error(`集合不存在：${normalized}`);
      error.statusCode = 404;
      throw error;
    }
    return this.client.getCollection({ name, embeddingFunction: null });
  }

  async createCollection({ name, displayName }) {
    const key = normalizeCollectionKey(name);
    const tableName = tableCollectionName(key);
    if (await this.client.hasCollection(tableName)) {
      const error = new Error(`集合已存在：${key}`);
      error.statusCode = 409;
      throw error;
    }
    const display = String(displayName || displayNameFromKey(key)).slice(0, 200);
    await this.client.createCollection({ name: tableName, schema: this.schema() });
    await this.client.execute(
      `INSERT INTO kb_collections
        (name, display_name, model, dimension, dtype, doc_count, chunk_count)
       VALUES (?, ?, ?, ?, ?, 0, 0)`,
      [key, display, config.model.id, config.model.dimension, config.model.dtype],
    );
    return this.collectionInfo(key);
  }

  async deleteCollection(key) {
    const normalized = normalizeCollectionKey(key);
    if (normalized === normalizeCollectionKey(config.collection.defaultName)) {
      const error = new Error("默认集合不能删除，可以清空后继续使用");
      error.statusCode = 400;
      throw error;
    }
    const tableName = tableCollectionName(normalized);
    if (await this.client.hasCollection(tableName)) {
      await this.client.deleteCollection(tableName);
    }
    await this.client.execute("DELETE FROM kb_documents WHERE collection_name = ?", [
      normalized,
    ]);
    await this.client.execute("DELETE FROM kb_collections WHERE name = ?", [normalized]);
    return { ok: true };
  }

  async clearCollection(key) {
    const normalized = normalizeCollectionKey(key);
    const tableName = tableCollectionName(normalized);
    if (await this.client.hasCollection(tableName)) {
      await this.client.deleteCollection(tableName);
    }
    await this.client.createCollection({ name: tableName, schema: this.schema() });
    await this.client.execute("DELETE FROM kb_documents WHERE collection_name = ?", [
      normalized,
    ]);
    await this.client.execute(
      `UPDATE kb_collections
       SET doc_count = 0, chunk_count = 0, last_import_at = NULL, last_refresh_at = NULL,
           updated_at = CURRENT_TIMESTAMP
       WHERE name = ?`,
      [normalized],
    );
    return { ok: true };
  }

  async collectionInfo(key) {
    const rows = await this.client.execute(
      `SELECT name, display_name, model, dimension, dtype, doc_count, chunk_count,
              created_at, updated_at, last_import_at, last_refresh_at
       FROM kb_collections WHERE name = ?`,
      [key],
    );
    if (!rows || rows.length === 0) {
      const error = new Error(`集合不存在：${key}`);
      error.statusCode = 404;
      throw error;
    }
    const row = rows[0];
    return {
      name: row.name ?? row.NAME,
      displayName: row.display_name ?? row.DISPLAY_NAME,
      model: row.model ?? row.MODEL,
      dimension: Number(row.dimension ?? row.DIMENSION),
      dtype: row.dtype ?? row.DTYPE,
      docCount: Number(row.doc_count ?? row.DOC_COUNT),
      chunkCount: Number(row.chunk_count ?? row.CHUNK_COUNT),
      createdAt: toIso(row.created_at ?? row.CREATED_AT),
      updatedAt: toIso(row.updated_at ?? row.UPDATED_AT),
      lastImportAt: toIso(row.last_import_at ?? row.LAST_IMPORT_AT),
      lastRefreshAt: toIso(row.last_refresh_at ?? row.LAST_REFRESH_AT),
    };
  }

  async listCollections() {
    const rows = await this.client.execute(
      `SELECT name FROM kb_collections ORDER BY (name = ?) DESC, created_at ASC`,
      [normalizeCollectionKey(config.collection.defaultName)],
    );
    const result = [];
    for (const row of rows || []) {
      try {
        result.push(await this.collectionInfo(row.name ?? row.NAME));
      } catch {
        // A dropped collection row can be ignored; the metadata is repaired on
        // the next create/import.
      }
    }
    return result;
  }

  async listDocuments(key, limit = 200) {
    const normalized = normalizeCollectionKey(key);
    const rows = await this.client.execute(
      `SELECT doc_id, title, source_name, tags, chunk_count, imported_at
       FROM kb_documents WHERE collection_name = ?
       ORDER BY imported_at DESC LIMIT ?`,
      [normalized, Math.min(Math.max(Number(limit) || 200, 1), 1000)],
    );
    return (rows || []).map((row) => {
      let tags = row.tags ?? row.TAGS;
      if (typeof tags === "string") {
        try {
          tags = JSON.parse(tags);
        } catch {
          tags = [];
        }
      }
      return {
        id: row.doc_id ?? row.DOC_ID,
        title: row.title ?? row.TITLE,
        source: row.source_name ?? row.SOURCE_NAME,
        tags: Array.isArray(tags) ? tags : [],
        chunkCount: Number(row.chunk_count ?? row.CHUNK_COUNT),
        importedAt: toIso(row.imported_at ?? row.IMPORTED_AT),
      };
    });
  }

  async importDocuments(key, { documents, embeddings, model, dtype, refresh = true }) {
    const normalized = normalizeCollectionKey(key);
    const col = await this.collection(normalized);
    assert(Array.isArray(documents) && documents.length > 0, "没有可写入的文档");
    assert(Array.isArray(embeddings), "缺少向量数组");
    assert(
      documents.length === embeddings.length,
      `文档数 (${documents.length}) 与向量数 (${embeddings.length}) 不一致`,
    );
    assert(
      documents.length <= config.limits.maxDocumentsPerImport,
      `单次最多导入 ${config.limits.maxDocumentsPerImport} 个分块`,
    );

    const ids = [];
    const texts = [];
    const vectors = [];
    const metadatas = [];
    const docsById = new Map();

    for (let i = 0; i < documents.length; i += 1) {
      const doc = documents[i];
      const vector = embeddings[i];
      assert(doc && typeof doc === "object", `文档 ${i} 格式错误`);
      assert(typeof doc.id === "string" && doc.id.length > 0, `文档 ${i} 缺少 id`);
      assert(typeof doc.text === "string" && doc.text.trim().length > 0, `文档 ${i} 缺少正文`);
      assert(doc.text.length <= config.limits.maxTextChars, `文档 ${i} 正文过长`);
      assert(Array.isArray(vector), `文档 ${i} 向量格式错误`);
      assert(
        vector.length === config.model.dimension,
        `文档 ${i} 向量维度 ${vector.length}，期望 ${config.model.dimension}`,
      );
      for (const value of vector) {
        assert(Number.isFinite(value), `文档 ${i} 向量包含非数值`);
      }
      const docId = String(doc.docId || doc.id).slice(0, 120);
      const title = String(doc.title || "未命名文档").slice(0, 280);
      const tags = Array.isArray(doc.tags)
        ? doc.tags.map((tag) => String(tag).slice(0, 40)).slice(0, 10)
        : [];
      ids.push(String(doc.id).slice(0, 200));
      texts.push(doc.text);
      vectors.push(vector);
      metadatas.push({
        docId,
        title,
        source: String(doc.source || "").slice(0, 480),
        chunkIndex: Number(doc.chunkIndex || 0),
        tags,
        importedAt: new Date().toISOString(),
      });
      const current = docsById.get(docId) || {
        docId,
        title,
        source: String(doc.source || "").slice(0, 480),
        tags,
        chunkCount: 0,
      };
      current.chunkCount += 1;
      docsById.set(docId, current);
    }

    const t0 = nowMs();
    const batchSize = 32;
    for (let start = 0; start < ids.length; start += batchSize) {
      const end = Math.min(start + batchSize, ids.length);
      await col.upsert({
        ids: ids.slice(start, end),
        documents: texts.slice(start, end),
        embeddings: vectors.slice(start, end),
        metadatas: metadatas.slice(start, end),
      });
    }
    const writeMs = nowMs() - t0;

    let refreshMs = 0;
    if (refresh) {
      const t1 = nowMs();
      await col.refresh_index();
      refreshMs = nowMs() - t1;
    }

    for (const doc of docsById.values()) {
      await this.client.execute(
        `INSERT INTO kb_documents
           (collection_name, doc_id, title, source_name, tags, chunk_count, imported_at)
         VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
         ON DUPLICATE KEY UPDATE
           title = VALUES(title), source_name = VALUES(source_name),
           tags = VALUES(tags), chunk_count = VALUES(chunk_count),
           imported_at = CURRENT_TIMESTAMP`,
        [
          normalized,
          doc.docId,
          doc.title,
          doc.source,
          JSON.stringify(doc.tags),
          doc.chunkCount,
        ],
      );
    }

    const counts = await this.client.execute(
      `SELECT COUNT(*) AS doc_count, COALESCE(SUM(chunk_count), 0) AS chunk_count
       FROM kb_documents WHERE collection_name = ?`,
      [normalized],
    );
    const countRow = counts?.[0] || {};
    const docCount = Number(countRow.doc_count ?? countRow.DOC_COUNT ?? docsById.size);
    const chunkCount = Number(countRow.chunk_count ?? countRow.CHUNK_COUNT ?? ids.length);
    await this.client.execute(
      `UPDATE kb_collections
       SET doc_count = ?, chunk_count = ?, model = ?, dtype = ?,
           last_import_at = CURRENT_TIMESTAMP,
           last_refresh_at = ${refresh ? "CURRENT_TIMESTAMP" : "last_refresh_at"},
           updated_at = CURRENT_TIMESTAMP
       WHERE name = ?`,
      [docCount, chunkCount, String(model || config.model.id), String(dtype || config.model.dtype), normalized],
    );

    const total = await col.count();
    return {
      collection: normalized,
      insertedChunks: ids.length,
      docCount,
      chunkCount,
      collectionCount: total,
      writeMs: Math.round(writeMs * 10) / 10,
      refreshMs: Math.round(refreshMs * 10) / 10,
      totalMs: Math.round((nowMs() - t0) * 10) / 10,
    };
  }

  async search(key, { query, embedding, topK = 8 }) {
    const normalized = normalizeCollectionKey(key);
    const col = await this.collection(normalized);
    assert(Array.isArray(embedding), "缺少查询向量");
    assert(
      embedding.length === config.model.dimension,
      `查询向量维度 ${embedding.length}，期望 ${config.model.dimension}`,
    );
    for (const value of embedding) assert(Number.isFinite(value), "查询向量包含非数值");
    const safeQuery = normalizeQueryText(query);
    const k = Math.min(Math.max(Number(topK) || 8, 1), config.limits.maxTopK);

    const started = nowMs();
    const options = {
      knn: {
        queryEmbeddings: [embedding],
        nResults: Math.max(k * 2, 20),
      },
      rank: { rrf: { rankWindowSize: Math.max(k * 4, 40), rankConstant: 60 } },
      nResults: k,
      include: ["documents", "metadatas", "distances"],
    };
    if (safeQuery) {
      options.query = { whereDocument: { $contains: safeQuery } };
    }
    const result = await col.hybridSearch(options);
    const searchMs = nowMs() - started;

    const ids = result.ids?.[0] || [];
    const documents = result.documents?.[0] || [];
    const metadatas = result.metadatas?.[0] || [];
    const distances = result.distances?.[0] || [];
    const hits = ids.map((id, index) => {
      const meta = metadatas[index] || {};
      return {
        id,
        text: documents[index] || "",
        score: Number(distances[index] ?? 0),
        title: meta.title || "未命名文档",
        docId: meta.docId || "",
        source: meta.source || "",
        chunkIndex: Number(meta.chunkIndex || 0),
        tags: Array.isArray(meta.tags) ? meta.tags : [],
        rank: index + 1,
      };
    });
    return {
      query: String(query || ""),
      normalizedQuery: safeQuery,
      hits,
      topK: k,
      searchMs: Math.round(searchMs * 10) / 10,
      engine: "seekdb DBMS_HYBRID_SEARCH (RRF)",
      rank: { rrf: { rankWindowSize: Math.max(k * 4, 40), rankConstant: 60 } },
    };
  }

  async health() {
    const started = nowMs();
    await this.client.execute("SELECT 1 AS ok");
    const pingMs = nowMs() - started;
    let version = "unknown";
    try {
      const rows = await this.client.execute("SELECT VERSION() AS version");
      version = rows?.[0]?.version ?? rows?.[0]?.VERSION ?? "unknown";
    } catch {
      // optional
    }
    return {
      ok: true,
      backend: this.backend,
      mode: this.mode,
      version,
      pingMs: Math.round(pingMs * 10) / 10,
      database: config.seekdb.database,
      host: this.mode === "server" ? `${config.seekdb.host}:${config.seekdb.port}` : "embedded",
      startedAt: this.startedAt,
    };
  }
}

export const store = new KBStore();
