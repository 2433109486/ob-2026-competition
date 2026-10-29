import { chromium } from "playwright-core";

const edge =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const base = process.env.BASE_URL || "http://127.0.0.1:5173";
const suffix = Date.now().toString(36);
const collection = `accept_${suffix}`;
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(String(error)));
const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
}
try {
  await page.goto(`${base}/?backend=wasm&dtype=q8`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => window.__SEEKBASE__.ready);

  await page.evaluate(async (collection) => {
    const create = await fetch("/api/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: collection, displayName: "验收临时知识库" }),
    });
    if (!create.ok) throw new Error(await create.text());
    await window.__SEEKBASE__.switchCollection(collection);
  }, collection);
  check("创建并切换集合", true, collection);

  await page.evaluate(async () => {
    await window.__SEEKBASE__.importDocs([
      {
        id: "quantum",
        title: "量子纠缠实验记录",
        source: "acceptance/quantum.md",
        tags: ["物理"],
        text: "量子纠缠实验使用自发参量下转换产生纠缠光子对。测量其中一个光子的偏振，另一个光子的状态会瞬时关联。实验记录了符合计数和贝尔不等式违背。",
      },
      {
        id: "cookie",
        title: "巧克力曲奇配方",
        source: "acceptance/cookie.md",
        tags: ["烘焙"],
        text: "巧克力曲奇需要低筋面粉、黄油、红糖和黑巧克力。黄油软化后打发，加入鸡蛋和面粉，烤箱一百八十度烘烤十二分钟。",
      },
    ]);
  });
  let state = await page.evaluate(() => window.__SEEKBASE__.getState());
  check("首次增量导入两篇", state.collection.docCount === 2 && state.collection.chunkCount === 2, JSON.stringify(state.lastImport));
  check("首次导入后刷新自检", state.lastImport?.verified === true);

  const quantum = await page.evaluate(async () => {
    await window.__SEEKBASE__.search("量子纠缠 贝尔不等式");
    return window.__SEEKBASE__.getState().lastSearch;
  });
  check("检索量子文档命中 top1", quantum.hits[0]?.docId === "quantum", quantum.hits[0]?.title);

  await page.evaluate(async () => {
    await window.__SEEKBASE__.importDocs([
      {
        id: "hydrothermal",
        title: "深海热泉生态系统",
        source: "acceptance/deepsea.md",
        tags: ["生物"],
        text: "深海热泉附近没有阳光，化能合成细菌利用硫化氢制造有机物，支撑管虫、贻贝和盲虾群落。热泉喷口温度可达三百摄氏度。",
      },
    ]);
  });
  const after = await page.evaluate(async () => {
    await window.__SEEKBASE__.search("深海热泉 化能合成");
    return {
      search: window.__SEEKBASE__.getState().lastSearch,
      collection: window.__SEEKBASE__.getState().collection,
      lastImport: window.__SEEKBASE__.getState().lastImport,
    };
  });
  check("增量导入第三篇", after.collection.docCount === 3 && after.collection.chunkCount === 3, JSON.stringify(after.lastImport));
  check("新增文档刷新后可检索", after.search.hits[0]?.docId === "hydrothermal", after.search.hits[0]?.title);

  const switched = await page.evaluate(async (collection) => {
    await window.__SEEKBASE__.switchCollection("default");
    await window.__SEEKBASE__.search("深海热泉 化能合成");
    const defaultSearch = window.__SEEKBASE__.getState().lastSearch;
    await window.__SEEKBASE__.switchCollection(collection);
    return {
      defaultHits: defaultSearch.hits.map((hit) => hit.docId),
      current: window.__SEEKBASE__.getState().collection,
    };
  }, collection);
  check(
    "切换到默认集合后不残留临时集合结果",
    !switched.defaultHits.includes("hydrothermal"),
    JSON.stringify(switched.defaultHits.slice(0, 5)),
  );
  check("切回临时集合状态正确", switched.current.name === collection && switched.current.docCount === 3);

  const cleanup = await page.evaluate(async (collection) => {
    await window.__SEEKBASE__.switchCollection("default");
    const response = await fetch(`/api/collections/${encodeURIComponent(collection)}`, { method: "DELETE" });
    return response.ok;
  }, collection);
  check("删除临时集合", cleanup);
  check("浏览器无运行时错误", errors.length === 0, errors.slice(0, 3).join(" | "));

  const failed = results.filter((item) => !item.ok);
  console.log(JSON.stringify({ collection, passed: results.length - failed.length, failed: failed.length, results }, null, 2));
  process.exitCode = failed.length ? 1 : 0;
} finally {
  await browser.close();
}
