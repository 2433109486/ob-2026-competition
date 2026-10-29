import test from "node:test";
import assert from "node:assert/strict";
import { chunkText, makeChunks, parseFiles, extractTitle } from "../web/lib/chunk.js";
import { mrrAtK, ndcgAtK, recallAtK, uniqueDocIds } from "../web/lib/metrics.js";

test("chunkText keeps paragraphs and respects the configured window", () => {
  const paragraph = "端侧推理需要在浏览器内完成。".repeat(30);
  const chunks = chunkText(paragraph, { maxChars: 120, overlap: 20 });
  assert.ok(chunks.length > 2);
  for (const chunk of chunks) {
    assert.ok(chunk.length <= 150, `chunk too long: ${chunk.length}`);
  }
});

test("makeChunks produces stable ids for idempotent imports", () => {
  const doc = {
    id: "paper-1",
    title: "检索笔记",
    text: "混合检索把向量召回和全文召回放在数据库内融合。".repeat(10),
    source: "notes/paper.md",
  };
  const first = makeChunks(doc, { maxChars: 100, overlap: 20 });
  const second = makeChunks(doc, { maxChars: 100, overlap: 20 });
  assert.deepEqual(first.map((chunk) => chunk.id), second.map((chunk) => chunk.id));
  assert.equal(first[0].docId, "paper-1");
});

test("extractTitle prefers markdown heading", () => {
  assert.equal(extractTitle("# 标题\n正文"), "标题");
  assert.equal(extractTitle("第一行\n第二行", "fallback"), "第一行");
});

test("parseFiles supports markdown and JSON arrays", async () => {
  const markdown = new File(["# 笔记\n\nseekdb 混合检索"], "note.md", { type: "text/markdown" });
  const json = new File(
    [JSON.stringify([{ id: "x", title: "JSON 文档", text: "全文与向量" }])],
    "docs.json",
    { type: "application/json" },
  );
  const docs = await parseFiles([markdown, json]);
  assert.equal(docs.length, 2);
  assert.equal(docs[0].title, "笔记");
  assert.equal(docs[1].id, "x");
});

test("retrieval metrics handle graded relevance and duplicate chunks", () => {
  const hits = [
    { docId: "a" },
    { docId: "a" },
    { docId: "b" },
    { docId: "c" },
    { docId: "d" },
  ];
  const relevant = { a: 2, b: 1, z: 1 };
  assert.deepEqual(uniqueDocIds(hits), ["a", "b", "c", "d"]);
  assert.equal(recallAtK(hits, relevant, 5), 2 / 3);
  assert.equal(mrrAtK(hits, relevant, 10), 1);
  assert.ok(ndcgAtK(hits, relevant, 5) > 0.8);
  assert.ok(ndcgAtK(hits, relevant, 5) <= 1);
  assert.equal(recallAtK([{ docId: "x" }], relevant, 5), 0);
});
