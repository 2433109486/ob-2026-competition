/* 研脉 ResearchPulse — single-page research workspace.
   No framework, no build step. All data comes from the local FastAPI service. */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const state = {
  bootstrap: null,
  papers: [],
  papersLoaded: false,
  search: null,
  searchLoading: false,
  query: "",
  filters: { tags: [], status: "all", year_min: "", year_max: "", source_type: "all" },
  library: { status: "", tag: "", q: "" },
  librarySelected: new Set(),
  reviewPapers: [],
  allPapers: [],
  reviewSelected: new Set(),
  reviewQuestion: "",
  review: null,
  reviewLoaded: false,
  matrixEditing: false,
  memory: null,
  profile: null,
  paper: null,
  paperDraft: null,
  paperTab: "read",
  focusSearch: false,
};

const VIEW_META = {
  today: { label: "今日", crumb: "今日" },
  search: { label: "证据检索", crumb: "证据检索" },
  library: { label: "资料库", crumb: "资料库" },
  review: { label: "综述矩阵", crumb: "综述矩阵" },
  memory: { label: "研究记忆", crumb: "研究记忆" },
};

const STATUS_LABEL = { read: "已精读", reading: "精读中", to_read: "待读" };
const FIELD_LABEL = {
  problem: "研究问题",
  method: "研究设计",
  sample: "样本 / 情境",
  finding: "主要发现",
  limitation: "局限",
  reuse: "可复用点",
};

// ------------------------------------------------------------------ utilities
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}

function icon(name, cls = "") {
  return `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

function tagTone(tag, index = 0) {
  const tones = ["", "coral", "gold", "plain"];
  return tones[(String(tag).length + index) % tones.length];
}

function tagsHtml(tags, limit = 4) {
  return (tags || [])
    .slice(0, limit)
    .map((tag, index) => `<span class="tag ${tagTone(tag, index)}">${escapeHtml(tag)}</span>`)
    .join("");
}

function statusPill(status) {
  return `<span class="status-pill status-${escapeAttr(status || "to_read")}">${STATUS_LABEL[status] || "待读"}</span>`;
}

function formatDate(value, withTime = false) {
  if (!value) return "—";
  const date = parseDate(value);
  if (!date) return String(value).slice(0, 10);
  const options = withTime
    ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "2-digit", day: "2-digit" };
  return new Intl.DateTimeFormat("zh-CN", options).format(date);
}

function relativeTime(value) {
  if (!value) return "";
  const date = parseDate(value);
  if (!date) return "";
  const diff = Date.now() - date.getTime();
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} 天前`;
  return formatDate(value);
}

function parseDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  let text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) text = text.replace(" ", "T") + "Z";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function todayLabel() {
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(new Date());
}

function initials(name) {
  return String(name || "研").trim().slice(0, 1) || "研";
}

function quote(text) {
  return escapeHtml(text || "").replaceAll("\n", "<br>");
}

function emptyState(title, body, action = "") {
  return `<div class="empty-state"><div class="empty-icon">${icon("book")}</div><h4>${escapeHtml(title)}</h4><p>${escapeHtml(body)}</p>${action}</div>`;
}

function toast(message, type = "ok") {
  const root = $("#toast-root");
  const node = document.createElement("div");
  node.className = `toast ${type === "error" ? "error" : ""}`;
  node.innerHTML = `${icon(type === "error" ? "alert" : "check")}<span>${escapeHtml(message)}</span>`;
  root.appendChild(node);
  window.setTimeout(() => {
    node.classList.add("out");
    window.setTimeout(() => node.remove(), 220);
  }, 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  return response.text();
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").split("\n");
  const html = [];
  let inList = false;
  let inQuote = false;
  const inline = (text) =>
    escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\[(\d+)\]/g, '<span class="cite">[$1]</span>');

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      if (inList) { html.push("</ol>"); inList = false; }
      if (inQuote) { html.push("</blockquote>"); inQuote = false; }
      continue;
    }
    if (line.startsWith("# ")) {
      html.push(`<h1>${inline(line.slice(2))}</h1>`);
    } else if (line.startsWith("## ")) {
      html.push(`<h2>${inline(line.slice(3))}</h2>`);
    } else if (line.startsWith("> ")) {
      if (!inQuote) { html.push("<blockquote>"); inQuote = true; }
      html.push(`<p>${inline(line.slice(2))}</p>`);
    } else if (/^\[\d+\]/.test(line)) {
      if (!inList) { html.push("<ol>"); inList = true; }
      html.push(`<li>${inline(line.replace(/^\[\d+\]\s*/, ""))}</li>`);
    } else {
      if (inList) { html.push("</ol>"); inList = false; }
      html.push(`<p>${inline(line)}</p>`);
    }
  }
  if (inList) html.push("</ol>");
  if (inQuote) html.push("</blockquote>");
  return html.join("");
}

// ------------------------------------------------------------------ boot
async function init() {
  bindEvents();
  try {
    await refreshBootstrap();
    await routeFromHash();
  } catch (error) {
    $("#view").innerHTML = `<div class="page"><div class="empty-state"><div class="empty-icon">${icon("alert")}</div><h4>暂时连接不上本地服务</h4><p>${escapeHtml(error.message)}。请确认 seekdb（2881）与 FastAPI（7860）已经启动，然后刷新页面。</p><button class="btn btn-primary" data-action="retry-boot">${icon("refresh")}重新连接</button></div></div>`;
  }
}

async function refreshBootstrap() {
  const data = await api("/api/bootstrap");
  state.bootstrap = data;
  updateShell(data);
}

function updateShell(data) {
  const profile = data.profile || {};
  const name = profile.name || "研究者";
  $("#sidebar-name").textContent = name;
  $("#sidebar-stage").textContent = profile.stage || "研究进行中";
  $("#sidebar-avatar").textContent = initials(name);
  $("#top-avatar").textContent = initials(name);
  $("#nav-paper-count").textContent = data.counts?.papers ?? "—";
  $("#nav-memory-count").textContent = data.memory_count ?? "—";
  const pcOk = Boolean(data.memory_available);
  const dbOk = Boolean(data.system?.seekdb?.ok);
  $("#pc-status-text").textContent = pcOk ? "研究记忆已同步" : "研究记忆未连接";
  $("#pc-orb").className = `status-orb ${pcOk ? "ok" : "bad"}`;
  const chip = $("#health-chip");
  chip.innerHTML = `<span class="status-orb ${dbOk && pcOk ? "ok" : dbOk ? "bad" : "bad"}"></span><span>${dbOk && pcOk ? "本地 · 就绪" : dbOk ? "记忆降级" : "连接异常"}</span>`;
}

async function routeFromHash() {
  const raw = (location.hash || "#/today").replace(/^#\/?/, "").split("?")[0] || "today";
  const route = VIEW_META[raw] ? raw : "today";
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.route === route));
  $("#crumb-current").textContent = VIEW_META[route].crumb;
  closeSidebar();
  if (route === "today") renderToday();
  if (route === "search") renderSearch();
  if (route === "library") await openLibrary();
  if (route === "review") await openReview();
  if (route === "memory") await openMemory();
}

function navigate(route) {
  if (location.hash === `#/${route}`) return routeFromHash();
  location.hash = `#/${route}`;
}

// ------------------------------------------------------------------ today
function renderToday() {
  const data = state.bootstrap;
  if (!data) return;
  const profile = data.profile || {};
  const counts = data.counts || {};
  const usage = data.usage || {};
  const focusPaper = data.continue_reading || data.recommended?.[0]?.paper;
  const focusMemory = focusPaper ? (data.continue_reading?.memory || null) : null;
  const focusTitle = focusPaper ? focusPaper.title : profile.question || "先建立你的研究问题";
  const focusMeta = focusPaper
    ? `${focusPaper.authors?.split(",")[0] || "未知作者"} · ${focusPaper.year || ""} · ${focusPaper.venue || ""}`
    : "从资料库导入第一篇文献，研脉会开始记住你的阅读路径。";
  const focusTag = focusPaper?.tags?.[0] || "研究问题";
  const recCards = (data.recommended || []).map((item, index) => {
    const paper = item.paper;
    return `<button class="paper-mini" type="button" data-action="open-paper" data-paper-id="${escapeAttr(paper.paper_id)}">
      <div class="paper-mini-top">
        <span class="tag ${index === 0 ? "coral" : index === 1 ? "gold" : ""}">${escapeHtml(item.why?.[0] || "推荐")}</span>
        <span class="paper-mini-year">${escapeHtml(paper.year || "")}</span>
      </div>
      <h4>${escapeHtml(paper.title)}</h4>
      <p>${escapeHtml(paper.abstract || "")}</p>
      <div class="paper-mini-foot">${icon("arrow-up-right")}${escapeHtml(paper.venue || "打开精读")}</div>
    </button>`;
  }).join("");

  const activity = (data.recent_activity || []).map((item) => {
    const icons = { search: "search", reading: "book", note: "note", review: "table", profile: "brain", seed: "layers", memory: "brain" };
    return `<div class="activity-item">
      <div class="activity-icon">${icon(icons[item.kind] || "clock")}</div>
      <div class="activity-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail?.results != null ? `${item.detail.results} 条结果` : item.detail?.coverage != null ? `覆盖率 ${item.detail.coverage}%` : "已记录")}</small></div>
      <span class="activity-time">${relativeTime(item.created_at)}</span>
    </div>`;
  }).join("") || `<div class="activity-copy"><small>还没有活动记录。检索一次，研脉会把过程写进研究记忆。</small></div>`;

  const topTags = (data.tags || []).slice(0, 5);
  const maxTag = Math.max(1, ...topTags.map((item) => item.count));
  const topicBars = topTags.map((item) => `<div class="topic-bar"><span>${escapeHtml(item.name)}</span><div class="topic-bar-track"><div class="topic-bar-fill" style="width:${Math.round((item.count / maxTag) * 100)}%"></div></div><strong>${item.count}</strong></div>`).join("");
  const tagCloud = (data.tags || []).slice(0, 9).map((item) => `<button class="tag" type="button" data-action="search-tag" data-tag="${escapeAttr(item.name)}">${escapeHtml(item.name)} <small>${item.count}</small></button>`).join("");

  $("#view").innerHTML = `<section class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">RESEARCH DESK · ${escapeHtml(todayLabel())}</div>
        <h1 class="display-title">${escapeHtml(data.greeting || "你好")}，<em>${escapeHtml(profile.name || "研究者")}</em>。</h1>
        <p class="lede">把散落的文献、证据和判断，连成一条可以回头核对的研究脉络。你的画像、阅读进度和综述决策，都已经被记住。</p>
      </div>
      <div class="page-head-actions">
        <button class="btn" type="button" data-action="open-profile">${icon("user")}研究画像</button>
        <button class="btn btn-primary" type="button" data-action="focus-search">${icon("search")}开始检索</button>
      </div>
    </div>

    <div class="hero-grid">
      <article class="focus-card">
        <div class="focus-top"><span class="focus-label">今日聚焦</span><span class="focus-date">${escapeHtml(todayLabel())}</span></div>
        <h2 class="focus-question">${focusPaper ? `继续读：<span class="accent">${escapeHtml(focusTitle)}</span>` : escapeHtml(focusTitle)}</h2>
        <div class="focus-bottom">
          <div class="focus-meta"><span class="tag coral">${escapeHtml(focusTag)}</span><span>${escapeHtml(focusMeta)}</span></div>
          <div class="focus-actions">
            ${focusPaper ? `<button class="btn btn-primary" type="button" data-action="open-paper" data-paper-id="${escapeAttr(focusPaper.paper_id)}">${icon("book")}${focusMemory?.status === "reading" ? "继续精读" : "打开"} </button>` : `<button class="btn btn-primary" type="button" data-action="focus-search">${icon("search")}找第一篇</button>`}
            <button class="btn" type="button" data-action="nav" data-route="search">检索证据</button>
          </div>
        </div>
      </article>

      <article class="panel memory-card">
        <div class="memory-orb">${icon("brain")}</div>
        <h3>研究记忆，不是聊天记录</h3>
        <p>PowerContext 记住的是你已经确认的判断和进度，下一次检索会带着它们一起工作。</p>
        <div class="memory-facts">
          <div class="memory-fact"><span>研究阶段</span><strong>${escapeHtml(profile.stage || "未设置")}</strong></div>
          <div class="memory-fact"><span>关注主题</span><strong>${escapeHtml((profile.focus_tags || []).slice(0, 3).join(" · ") || "未设置")}</strong></div>
          <div class="memory-fact"><span>已写入记忆</span><strong>${data.memory_count || 0} 条</strong></div>
        </div>
        <button class="link-button" type="button" data-action="nav" data-route="memory">看看它如何影响下一次检索 →</button>
      </article>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="stat-top">${icon("library")}资料库</div><div class="stat-value">${counts.papers || 0}<small>份</small></div><div class="stat-foot">${counts.chunks || 0} 个证据片段已建索引</div></div>
      <div class="stat-card"><div class="stat-top">${icon("book")}已精读</div><div class="stat-value">${counts.read || 0}<small>篇</small></div><div class="stat-foot">${counts.reading || 0} 篇正在精读</div></div>
      <div class="stat-card"><div class="stat-top">${icon("clock")}待读队列</div><div class="stat-value">${counts.to_read || 0}<small>篇</small></div><div class="stat-foot">按研究画像排了优先级</div></div>
      <div class="stat-card"><div class="stat-top">${icon("search")}本周检索</div><div class="stat-value">${usage.searches || 0}<small>次</small></div><div class="stat-foot">${usage.searches ? `平均 ${usage.avg_latency_ms} ms · 记忆参与 ${usage.memory_searches || 0} 次` : "检索一次，建立第一条证据链"}</div></div>
    </div>

    <div class="recommend-section">
      <div class="panel-head mb-0">
        <div><div class="panel-kicker">FROM YOUR MEMORY</div><h2 class="section-title">从记忆里长出来的建议</h2></div>
        <button class="link-button" type="button" data-action="nav" data-route="library">打开资料库 →</button>
      </div>
      <div class="recommend-grid">${recCards || emptyState("还没有推荐", "先补充研究画像，研脉会按你的主题和阶段排序待读文献。")}</div>
    </div>

    <div class="bottom-grid">
      <section class="panel panel-pad">
        <div class="panel-head"><div><div class="panel-kicker">RESEARCH LOG</div><h2 class="section-title">最近发生的事</h2></div><button class="link-button" type="button" data-action="nav" data-route="search">去检索 →</button></div>
        <div class="activity-list">${activity}</div>
      </section>
      <section class="panel panel-pad">
        <div class="panel-head"><div><div class="panel-kicker">TOPIC MAP</div><h2 class="section-title">主题正在往哪里长</h2></div></div>
        <div class="tag-cloud">${tagCloud || '<span class="muted tiny">还没有标签。</span>'}</div>
        <div class="topic-bars">${topicBars}</div>
      </section>
    </div>
  </section>`;
}

// ------------------------------------------------------------------ search
function renderSearch() {
  const data = state.bootstrap || {};
  const memory = state.search?.memory || {
    summary: data.profile?.field ? `${data.profile.field} · ${data.profile.stage}` : "尚未建立画像",
    focus_tags: data.profile?.focus_tags || [],
    in_progress: data.continue_reading ? [data.continue_reading] : [],
    related: [],
    available: data.memory_available,
  };
  const result = state.search;
  const tags = (data.tags || []).slice(0, 7);
  const filterTags = tags.map((item) => `<button class="filter-chip ${state.filters.tags.includes(item.name) ? "active" : ""}" type="button" data-action="filter-tag" data-tag="${escapeAttr(item.name)}">${escapeHtml(item.name)}</button>`).join("");
  const examples = [
    "AI 编程助手对初学者学习迁移的影响",
    "怎么避免学生直接抄答案",
    "主动学习 认知参与 框架",
    "非英语母语 编程学习 障碍",
  ];
  const resultsHtml = state.searchLoading
    ? `<div class="results-list">${[0, 1, 2].map(() => `<div class="skeleton skeleton-card"><div class="skeleton-line" style="width:52%;margin-bottom:10px"></div><div class="skeleton-line" style="width:84%;margin-bottom:7px"></div><div class="skeleton-line" style="width:70%"></div></div>`).join("")}</div>`
    : result
      ? renderResults(result)
      : renderSearchPrompt(data, examples);

  const recent = (data.recent_searches || []).slice(0, 3).map((item) => `<button class="example-chip" type="button" data-action="run-example" data-query="${escapeAttr(item.query)}">${escapeHtml(item.query.length > 22 ? item.query.slice(0, 22) + "…" : item.query)}</button>`).join("");

  $("#view").innerHTML = `<section class="page">
    <div class="page-head">
      <div><div class="eyebrow">EVIDENCE RETRIEVAL · SEEKDB</div><h1 class="display-title">检索证据，<br>而不是检索<em>关键词</em>。</h1><p class="lede">向量召回负责“意思相近”，ngram 全文召回负责“原话对得上”，融合后每条结果都带着出处、片段和为什么被选中。</p></div>
      <div class="page-head-actions"><span class="tag ${state.bootstrap?.memory_available ? "" : "coral"}">${icon("brain")} ${state.bootstrap?.memory_available ? "研究记忆参与排序" : "记忆降级，仅检索"}</span></div>
    </div>

    <div class="search-hero">
      <form class="search-form" id="search-form">
        ${icon("search")}
        <input class="search-input" id="search-input" name="query" value="${escapeAttr(state.query)}" placeholder="问一个问题，例如：AI 编程助手对初学者学习迁移的影响" autocomplete="off">
        <button class="btn btn-primary" type="submit">${icon("search")}<span>检索</span></button>
      </form>
      <div class="example-row"><span>试试：</span>${examples.map((query) => `<button class="example-chip" type="button" data-action="run-example" data-query="${escapeAttr(query)}">${escapeHtml(query)}</button>`).join("")}${recent ? `<span class="filter-divider"></span><span>最近：</span>${recent}` : ""}</div>
      <div class="filter-bar">
        <button class="filter-chip ${state.filters.tags.length ? "active" : ""}" type="button" data-action="toggle-filter-panel">${icon("filter")}筛选 ${state.filters.tags.length ? `· ${state.filters.tags.length}` : ""}</button>
        <span class="filter-divider"></span>
        ${filterTags}
        <button class="filter-chip filter-toggle ${state.filters.status !== "all" || state.filters.year_min || state.filters.year_max ? "active" : ""}" type="button" data-action="toggle-filter-panel">更多条件 ${icon("chevron-down")}</button>
      </div>
      <div class="filter-panel ${state.filtersPanel ? "open" : ""}" id="filter-panel">
        <div class="field"><label for="filter-status">阅读状态</label><select class="select" id="filter-status" data-filter="status"><option value="all">全部状态</option><option value="read" ${state.filters.status === "read" ? "selected" : ""}>已精读</option><option value="reading" ${state.filters.status === "reading" ? "selected" : ""}>精读中</option><option value="to_read" ${state.filters.status === "to_read" ? "selected" : ""}>待读</option></select></div>
        <div class="field"><label for="filter-year-min">起始年份</label><input class="input" id="filter-year-min" type="number" min="1990" max="2030" placeholder="不限" value="${escapeAttr(state.filters.year_min)}" data-filter="year_min"></div>
        <div class="field"><label for="filter-year-max">截止年份</label><input class="input" id="filter-year-max" type="number" min="1990" max="2030" placeholder="不限" value="${escapeAttr(state.filters.year_max)}" data-filter="year_max"></div>
        <div class="field"><label for="filter-type">资料类型</label><select class="select" id="filter-type" data-filter="source_type"><option value="all">论文与笔记</option><option value="paper" ${state.filters.source_type === "paper" ? "selected" : ""}>只看论文</option><option value="note" ${state.filters.source_type === "note" ? "selected" : ""}>只看笔记</option></select></div>
        <div class="field" style="grid-column:1/-1;flex-direction:row;justify-content:flex-end;gap:7px"><button class="btn btn-sm" type="button" data-action="clear-filters">清空筛选</button><button class="btn btn-sm btn-primary" type="button" data-action="apply-filters">应用条件</button></div>
      </div>
    </div>

    <div class="search-layout">
      <div class="search-main">${resultsHtml}</div>
      <aside class="search-aside">
        <div class="aside-card">
          <h4>${icon("brain")}本次记忆上下文</h4>
          <p>画像只改变排序与展示，不会伪造证据；每条结果仍来自 seekdb 的原文片段。</p>
          <div class="aside-profile"><strong>${escapeHtml(memory.summary || "尚未建立画像")}</strong><small>${memory.available ? "PowerContext 已参与本次检索" : "PowerContext 未连接，本次仅使用资料库"}</small></div>
          <div class="aside-tags">${(memory.focus_tags || []).slice(0, 6).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
          ${memory.in_progress?.length ? `<div class="aside-list">${memory.in_progress.slice(0, 2).map((item) => `<div class="aside-list-item"><b>正在精读</b>${escapeHtml(item.title || item.paper_id || "")}</div>`).join("")}</div>` : ""}
          ${memory.related?.length ? `<div class="aside-list">${memory.related.slice(0, 2).map((item) => `<div class="aside-list-item"><b>记忆命中 · ${escapeHtml(item.kind || "")}</b>${escapeHtml((item.summary || item.text || "").slice(0, 90))}…</div>`).join("")}</div>` : ""}
        </div>
        ${result ? `<div class="aside-card"><h4>${icon("database")}这次检索怎么发生</h4><p>${escapeHtml(result.counts.vector_candidates)} 个向量候选 · ${escapeHtml(result.counts.text_candidates)} 个全文候选，融合为 ${escapeHtml(result.counts.fused_chunks)} 个片段。</p><div class="aside-trace"><button class="btn btn-sm" type="button" data-action="open-trace">${icon("layers")}查看 SQL 轨迹</button></div></div>` : ""}
        ${!state.bootstrap?.memory_available ? `<div class="aside-card"><h4>${icon("alert")}记忆服务未连接</h4><p>启动 PowerContext 后刷新页面，画像、阅读进度与综述决策会重新参与排序。</p></div>` : ""}
      </aside>
    </div>
  </section>`;

  if (state.focusSearch) {
    state.focusSearch = false;
    window.setTimeout(() => $("#search-input")?.focus(), 80);
  }
}

function renderSearchPrompt(data, examples) {
  const recent = data.recent_searches || [];
  return `${emptyState("先问一个真正卡住你的问题", "比如“AI 提升的是练习表现还是学习迁移？”检索会同时走向量和全文两条路，并把证据片段摊开给你看。", `<button class="btn btn-primary" type="button" data-action="run-example" data-query="${escapeAttr(examples[0])}">${icon("sparkles")}用示例问题开始</button>`)}
    ${recent.length ? `<div class="panel panel-pad mt-14"><div class="panel-head"><div><div class="panel-kicker">RECENT SEARCHES</div><h2 class="section-title">最近的检索</h2></div></div><div class="tag-row">${recent.map((item) => `<button class="tag plain" type="button" data-action="run-example" data-query="${escapeAttr(item.query)}">${escapeHtml(item.query)} <small>${item.result_count}</small></button>`).join("")}</div></div>` : ""}`;
}

function renderResults(result) {
  const head = `<div class="results-head"><div class="results-title">找到 <span>${result.total}</span> 篇相关资料</div><div class="results-meta">${result.mode} · ${result.latency_ms} ms · ${result.counts.papers} papers</div></div>`;
  if (!result.results.length) {
    return `${head}${emptyState("没有找到匹配的证据", "试着减少筛选条件，或换一个更具体的说法。混合检索对“概念 + 场景”的问法更敏感。")}`;
  }
  const cards = result.results.map((item, index) => {
    const paper = item.paper;
    const score = Math.round(item.score * 100);
    const reasons = (item.reasons || []).map((reason) => `<span class="reason">${escapeHtml(reason)}</span>`).join("");
    const inReview = state.reviewSelected.has(paper.paper_id) || state.librarySelected.has(paper.paper_id);
    return `<article class="result-card">
      <div class="result-index">${String(index + 1).padStart(2, "0")}</div>
      <div class="result-body">
        <div class="result-meta">${statusPill(paper.status)}<span class="dot"></span><span>${escapeHtml(paper.venue || "未标注来源")}</span><span class="dot"></span><span>${escapeHtml(paper.year || "")}</span>${paper.source_type === "note" ? `<span class="tag gold">笔记</span>` : ""}</div>
        <h3 class="result-title" data-action="open-paper" data-paper-id="${escapeAttr(paper.paper_id)}">${escapeHtml(paper.title)}</h3>
        <p class="result-authors">${escapeHtml(paper.authors || "")}</p>
        <div class="snippet"><span class="snippet-section">${escapeHtml(item.best_chunk.section)}${item.best_chunk.page ? ` · ${escapeHtml(item.best_chunk.page)}` : ""}</span>${item.best_chunk.snippet_html}</div>
        <div class="result-reasons">${reasons}</div>
        <div class="result-actions">
          <button class="btn btn-sm" type="button" data-action="open-paper" data-paper-id="${escapeAttr(paper.paper_id)}">${icon("book")}打开精读</button>
          <button class="btn btn-sm" type="button" data-action="add-to-review" data-paper-id="${escapeAttr(paper.paper_id)}">${icon("plus")}${inReview ? "已在矩阵" : "加入综述"}</button>
          <button class="btn btn-sm btn-ghost" type="button" data-action="search-memory" data-query="${escapeAttr(result.query)}">${icon("brain")}记忆命中</button>
        </div>
      </div>
      <div class="result-score"><div class="score-ring" style="--score:${score}"><span>${score}</span></div><span class="score-label">融合分</span></div>
    </article>`;
  }).join("");
  return `${head}<div class="results-list">${cards}</div>`;
}

async function doSearch(query, remember = false) {
  const trimmed = String(query || "").trim();
  if (!trimmed) { toast("先写下要检索的问题", "error"); return; }
  state.query = trimmed;
  state.searchLoading = true;
  state.filtersPanel = false;
  renderSearch();
  try {
    const result = await api("/api/search", {
      method: "POST",
      body: JSON.stringify({
        query: trimmed,
        tags: state.filters.tags,
        year_min: state.filters.year_min ? Number(state.filters.year_min) : null,
        year_max: state.filters.year_max ? Number(state.filters.year_max) : null,
        status: state.filters.status,
        source_type: state.filters.source_type,
        limit: 12,
        remember,
        insight: remember ? "保留这次检索用于综述写作" : "",
      }),
    });
    state.search = result;
    state.searchLoading = false;
    if (remember) toast("已把这次检索写入研究记忆");
    if (state.bootstrap) {
      state.bootstrap.usage = { ...(state.bootstrap.usage || {}), searches: (state.bootstrap.usage?.searches || 0) + 1 };
    }
    renderSearch();
  } catch (error) {
    state.searchLoading = false;
    renderSearch();
    toast(error.message, "error");
  }
}

// ------------------------------------------------------------------ library
async function openLibrary() {
  ensureSearchShell();
  const data = state.bootstrap || {};
  const tagOptions = (data.tags || []).map((item) => `<option value="${escapeAttr(item.name)}" ${state.library.tag === item.name ? "selected" : ""}>${escapeHtml(item.name)} (${item.count})</option>`).join("");
  $("#view").innerHTML = `<section class="page">
    <div class="page-head">
      <div><div class="eyebrow">LIBRARY · ${data.counts?.papers || 0} RECORDS</div><h1 class="display-title">你的资料库，<br>应该<em>越用越清楚</em>。</h1><p class="lede">论文、组会纪要、研究设计都放在同一个可检索空间。每个条目都能回到原文片段、精读笔记和综述字段。</p></div>
      <div class="page-head-actions"><button class="btn" type="button" data-action="focus-search">${icon("search")}检索资料</button><button class="btn btn-primary" type="button" data-action="nav" data-route="review">${icon("table")}去搭矩阵</button></div>
    </div>
    <div class="library-toolbar">
      <div class="tab-row">
        ${[["", "全部"], ["reading", "精读中"], ["read", "已精读"], ["to_read", "待读"]].map(([value, label]) => `<button class="tab ${state.library.status === value ? "active" : ""}" type="button" data-action="library-status" data-status="${value}">${label}</button>`).join("")}
      </div>
      <select class="select" id="library-tag" style="width:132px;height:33px;font-size:10px" data-action="library-tag"><option value="">全部主题</option>${tagOptions}</select>
      <div class="library-search">${icon("search")}<input class="input" id="library-q" placeholder="搜标题、作者、摘要…" value="${escapeAttr(state.library.q)}"></div>
    </div>
    <div id="library-grid" class="paper-grid">${[0,1,2].map(() => `<div class="skeleton skeleton-card"></div>`).join("")}</div>
    <div id="selection-root"></div>
  </section>`;
  await loadLibraryPapers();
}

async function loadLibraryPapers() {
  const params = new URLSearchParams();
  if (state.library.q) params.set("q", state.library.q);
  if (state.library.status) params.set("status", state.library.status);
  if (state.library.tag) params.set("tag", state.library.tag);
  params.set("limit", "100");
  const data = await api(`/api/papers?${params.toString()}`);
  state.papers = data.items;
  state.papersLoaded = true;
  renderLibraryGrid();
}

function renderLibraryGrid() {
  const grid = $("#library-grid");
  if (!grid) return;
  if (!state.papers.length) {
    grid.innerHTML = emptyState("这个筛选下还没有资料", "换一个状态或主题，或者到检索页找新的证据。");
  } else {
    grid.innerHTML = state.papers.map((paper) => {
      const filled = Object.keys(FIELD_LABEL).filter((key) => String(paper[`review_${key}`] || "").length >= 6).length;
      const selected = state.librarySelected.has(paper.paper_id);
      return `<article class="paper-card ${selected ? "selected" : ""}" data-paper-card="${escapeAttr(paper.paper_id)}">
        <div class="paper-card-top">
          <button class="paper-check" type="button" data-action="toggle-select" data-paper-id="${escapeAttr(paper.paper_id)}" aria-label="${selected ? "从综述中移除" : "加入综述矩阵"}">${icon("check")}</button>
          <span class="paper-year">${escapeHtml(paper.year || "")}</span>
        </div>
        <h3><button type="button" data-action="open-paper" data-paper-id="${escapeAttr(paper.paper_id)}">${escapeHtml(paper.title)}</button></h3>
        <p class="paper-card-authors">${escapeHtml(paper.authors || "")}</p>
        <p class="paper-card-abstract">${escapeHtml(paper.abstract || "")}</p>
        <div class="paper-card-foot">
          <div class="tag-row">${tagsHtml(paper.tags, 3)}</div>
          <span class="paper-card-meta">${statusPill(paper.status)}<span class="priority-dot" title="优先级"></span>${filled}/6</span>
        </div>
      </article>`;
    }).join("");
  }
  renderSelectionBar();
}

function renderSelectionBar() {
  const root = $("#selection-root");
  if (!root) return;
  if (!state.librarySelected.size) { root.innerHTML = ""; return; }
  root.innerHTML = `<div class="selection-bar"><strong>已选 ${state.librarySelected.size} 篇，准备搭矩阵</strong><button class="btn btn-primary" type="button" data-action="selected-to-review">${icon("table")}生成综述矩阵</button><button class="btn btn-ghost" type="button" data-action="clear-library-selection">清空</button></div>`;
}

// ------------------------------------------------------------------ review
async function openReview() {
  ensureSearchShell();
  if (!state.allPapers.length) {
    const data = await api("/api/papers?limit=100");
    state.allPapers = data.items;
    if (!state.papersLoaded) {
      state.papers = data.items;
      state.papersLoaded = true;
    }
  }
  if (!state.reviewLoaded) {
    try {
      const memory = await api("/api/memory");
      state.memory = memory;
      if (memory.review?.paper_ids?.length) {
        state.reviewSelected = new Set(memory.review.paper_ids);
        state.reviewQuestion = memory.review.question || "";
      }
    } catch {
      /* keep empty selection */
    }
    state.reviewLoaded = true;
  }
  if (!state.reviewQuestion) state.reviewQuestion = state.bootstrap?.profile?.question || "";
  state.reviewPapers = state.allPapers;
  renderReview();
}

function renderReview() {
  const selected = state.reviewSelected;
  const list = state.reviewPapers.map((paper) => `<button class="select-item ${selected.has(paper.paper_id) ? "active" : ""}" type="button" data-action="toggle-review-paper" data-paper-id="${escapeAttr(paper.paper_id)}"><span class="paper-check">${icon("check")}</span><span class="select-copy"><strong>${escapeHtml(paper.title)}</strong><small>${escapeHtml(paper.year || "")} · ${escapeHtml(paper.venue || "未标注")}</small></span></button>`).join("");
  const matrixHtml = state.review ? renderMatrix(state.review) : `<div class="panel matrix-panel"><div class="review-placeholder">${emptyState("先选几篇，再压成一张表", "从左侧勾选 2–6 篇文献，研脉会把研究问题、设计、样本、发现、局限和可复用点排成矩阵，并生成一份可追溯的综述草稿。")}</div></div>`;
  $("#view").innerHTML = `<section class="page">
    <div class="page-head">
      <div><div class="eyebrow">SYNTHESIS · REVIEW MATRIX</div><h1 class="display-title">把读过的文献，<br>压成一张<em>能写的表</em>。</h1><p class="lede">矩阵只从你确认过的结构化字段抽取。每个单元格都能回到原文，也能直接编辑；覆盖度会提示哪里还没读透。</p></div>
      <div class="page-head-actions"><button class="btn" type="button" data-action="nav" data-route="library">${icon("library")}去资料库挑</button><button class="btn btn-primary" type="button" data-action="generate-review" ${selected.size ? "" : "disabled"}>${icon("sparkles")}生成 / 更新矩阵</button></div>
    </div>
    <div class="review-layout">
      <aside class="panel review-side panel-pad">
        <div class="panel-head"><div><div class="panel-kicker">SELECTED · ${selected.size}</div><h2 class="section-title">选进综述</h2></div><button class="link-button" type="button" data-action="select-all-review">全选</button></div>
        <div class="select-list">${list || '<p class="muted tiny">资料库为空。</p>'}</div>
        <hr class="divider">
        <div class="field"><label for="review-question">综述要回答的问题</label><textarea class="textarea" id="review-question" style="min-height:72px;font-size:11px" data-review-question>${escapeHtml(state.reviewQuestion)}</textarea></div>
        <button class="btn btn-primary mt-8" style="width:100%" type="button" data-action="generate-review" ${selected.size ? "" : "disabled"}>${icon("sparkles")}用这 ${selected.size} 篇生成</button>
        <p class="tiny muted mt-8" style="line-height:1.6">生成结果会写入 PowerContext 的「综述决策」，下次打开仍能恢复选择。</p>
      </aside>
      <div>${matrixHtml}</div>
    </div>
  </section>`;
}

function renderMatrix(result) {
  const matrix = result.matrix;
  const draft = result.draft;
  const rows = matrix.rows.map((row) => `<tr data-matrix-row="${escapeAttr(row.paper_id)}">
    <td><div class="matrix-paper"><span class="matrix-paper-index">${row.index}</span><span><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(row.authors?.split(",")[0] || "")} · ${escapeHtml(row.year || "")}</small></span></div></td>
    ${matrix.columns.map((column) => {
      const value = row.cells[column.key] || "";
      const missing = value.length < 6;
      return `<td class="matrix-cell ${missing ? "missing" : ""}" contenteditable="${state.matrixEditing}" data-paper-id="${escapeAttr(row.paper_id)}" data-field="${escapeAttr(column.key)}" data-placeholder="待补充">${value ? escapeHtml(value) : "待补充"}</td>`;
    }).join("")}
  </tr>`).join("");
  const gaps = matrix.gaps.length
    ? matrix.gaps.map((gap) => `<div class="gap-card"><strong>${escapeHtml(gap.label)} <span>${gap.filled}/${gap.total}</span></strong><p>${escapeHtml(gap.missing_titles.slice(0, 2).join("、"))}${gap.missing_titles.length > 2 ? " 等" : ""} 还没填。</p></div>`).join("")
    : `<div class="gap-card"><strong>六列已覆盖 <span>${matrix.coverage}%</span></strong><p>可以开始写“证据强度”与“研究空白”两节了。</p></div>`;
  return `<section class="panel matrix-panel">
    <div class="matrix-head">
      <div><div class="panel-kicker">MATRIX · ${matrix.paper_count} PAPERS</div><h2 class="section-title">${escapeHtml(matrix.question)}</h2><p class="section-sub">${matrix.empirical_count} 篇含实证/调查数据 · 覆盖度 ${matrix.coverage}%</p></div>
      <div class="coverage-wrap"><div class="coverage-track"><div class="coverage-fill" style="width:${matrix.coverage}%"></div></div><span class="coverage-value">${matrix.coverage}%</span></div>
    </div>
    <div class="matrix-scroll"><table class="matrix-table"><thead><tr><th>文献</th>${matrix.columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="matrix-actions">
      <button class="btn btn-sm" type="button" data-action="toggle-matrix-edit">${icon("note")}${state.matrixEditing ? "完成编辑" : "编辑单元格"}</button>
      ${state.matrixEditing ? `<span class="tiny muted">失焦即保存到 seekdb</span>` : ""}
      <span class="spacer"></span>
      <button class="btn btn-sm" type="button" data-action="save-review-memory">${icon("brain")}保存到记忆</button>
      <button class="btn btn-sm" type="button" data-action="export-review">${icon("download")}导出 Markdown</button>
      <button class="btn btn-sm btn-primary" type="button" data-action="generate-review">${icon("refresh")}重新生成</button>
    </div>
    <div class="panel-pad" style="border-top:1px solid var(--line)"><div class="gap-grid">${gaps}</div></div>
  </section>
  <section class="panel draft-panel">
    <div class="panel-head panel-pad" style="padding-bottom:14px"><div><div class="panel-kicker">TRACEABLE DRAFT</div><h2 class="section-title">综述初稿 · 可追溯</h2><p class="section-sub">每个判断都带引用编号；这是骨架，不是替你下结论。</p></div><div class="draft-meta"><span class="tag gold">${draft.paper_count} 篇</span><span class="tag">${draft.empirical_count} 篇实证</span><button class="btn btn-sm" type="button" data-action="copy-draft">${icon("copy")}复制</button></div></div>
    <div class="draft-body">${renderMarkdown(draft.markdown)}</div>
  </section>`;
}

// ------------------------------------------------------------------ memory
async function openMemory() {
  ensureSearchShell();
  try {
    state.memory = await api("/api/memory");
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  renderMemory();
}

function renderMemory() {
  const data = state.memory || {};
  const profile = data.profile || state.bootstrap?.profile || {};
  const timeline = (data.timeline || []).map((item) => `<div class="memory-item" data-kind="${escapeAttr(item.kind)}"><span class="memory-dot"></span><div class="memory-item-top"><span class="memory-kind">${escapeHtml(item.label || item.kind)}</span><span class="memory-time">${relativeTime(item.saved_at)}</span></div><p class="memory-text">${escapeHtml(item.text)}</p><div class="memory-ref">${escapeHtml(item.artifact_id || "—")} · rev ${escapeHtml(item.revision ?? "—")} · ${escapeHtml(item.state || "active")}</div></div>`).join("");
  const tags = (profile.focus_tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  const health = data.health || {};
  $("#view").innerHTML = `<section class="page">
    <div class="page-head"><div><div class="eyebrow">POWERCONTEXT · RESEARCH MEMORY</div><h1 class="display-title">研究记忆，<br>不是<em>聊天记录</em>。</h1><p class="lede">这里保存的是你确认过的方向、阅读进度和综述决策。它们会被下一次检索复用，而不是留在某一次对话里。</p></div><div class="page-head-actions"><button class="btn" type="button" data-action="open-profile">${icon("user")}编辑画像</button><button class="btn btn-primary" type="button" data-action="save-memory-memory">${icon("plus")}写一条记忆</button></div></div>
    <div class="memory-hero">
      <section class="panel profile-panel">
        <div class="profile-top"><span class="avatar profile-avatar">${escapeHtml(initials(profile.name))}</span><div><h2>${escapeHtml(profile.name || "研究者")}</h2><p>${escapeHtml(profile.field || "未设置领域")} · ${escapeHtml(profile.stage || "未设置阶段")}</p></div></div>
        <div class="profile-goal"><span>当前目标</span><strong>${escapeHtml(profile.goal || "还没有写下目标")}</strong></div>
        <div class="profile-grid">
          <div class="profile-field"><span>研究问题</span><strong>${escapeHtml(profile.question || "未设置")}</strong></div>
          <div class="profile-field"><span>方法偏好</span><strong>${escapeHtml((profile.methods || []).join(" · ") || "未设置")}</strong></div>
          <div class="profile-field"><span>关注主题</span><strong>${escapeHtml((profile.focus_tags || []).join(" · ") || "未设置")}</strong></div>
          <div class="profile-field"><span>写作偏好</span><strong>${escapeHtml((profile.preferences || []).join(" · ") || "未设置")}</strong></div>
        </div>
        <div class="tag-row mt-14">${tags}</div>
      </section>
      <section class="panel memory-status-card">
        <div class="memory-orb">${icon("brain")}</div>
        <div class="status-big"><span class="status-orb ${data.available ? "ok" : "bad"}"></span>${data.available ? "记忆已连接" : "记忆未连接"}</div>
        <p>${data.available ? "每次保存都会生成一个带 revision 的 Atomic Memory；新检索会读取最新画像与阅读进度。" : "启动 PowerContext 后刷新页面；已保存的 seekdb 资料不受影响。"}</p>
        <div class="memory-stat-row"><div class="memory-stat"><strong>${data.timeline?.length || 0}</strong><span>可见记忆</span></div><div class="memory-stat"><strong>${Object.keys(data.reading || {}).length}</strong><span>阅读进度</span></div></div>
        <div class="scope-line">${icon("link")} ${escapeHtml(data.scope_id || "尚未创建 Scope")}</div>
        <button class="btn btn-sm mt-14" type="button" data-action="open-pc" ${health.ok ? "" : "disabled"}>${icon("external")}打开 PowerContext</button>
      </section>
    </div>
    <div class="memory-layout">
      <section class="panel panel-pad">
        <div class="panel-head"><div><div class="panel-kicker">MEMORY TIMELINE</div><h2 class="section-title">最近被记住的事</h2></div><button class="link-button" type="button" data-action="refresh-memory">刷新 →</button></div>
        <div class="timeline">${timeline || emptyState("还没有记忆", "保存一次研究画像或阅读进度，时间线会从这里开始。")}</div>
      </section>
      <aside class="memory-aside">
        <div class="panel panel-pad">
          <div class="panel-kicker">HOW IT IS REUSED</div><h2 class="section-title" style="margin-top:4px">记忆如何影响工作</h2>
          <div class="memory-reuse">
            <div class="reuse-step"><span class="reuse-index">1</span><div><strong>保存画像</strong><small>领域、阶段、问题、方法与关注主题。</small></div></div>
            <div class="reuse-step"><span class="reuse-index">2</span><div><strong>改变检索排序</strong><small>相关主题与在读文献获得加权，但证据仍来自 seekdb 原文。</small></div></div>
            <div class="reuse-step"><span class="reuse-index">3</span><div><strong>恢复综述现场</strong><small>下次打开矩阵时，选择和问题被读回。</small></div></div>
          </div>
        </div>
        <div class="panel panel-pad">
          <div class="panel-kicker">RECALL TEST</div><h2 class="section-title" style="margin-top:4px">召回一条记忆</h2>
          <form class="recall-form" id="recall-form"><input class="input" id="recall-query" placeholder="例如：学习迁移"><button class="btn btn-primary" type="submit">召回</button></form>
          <div id="recall-results" class="recall-results"></div>
        </div>
        <div class="panel panel-pad">
          <div class="panel-kicker">WRITE A MEMORY</div><h2 class="section-title" style="margin-top:4px">写一条研究判断</h2>
          <form class="memory-note-form" id="memory-note-form"><textarea class="textarea" id="memory-note-text" placeholder="例如：主终点坚持用延迟迁移，不用课堂练习成绩替代。"></textarea><button class="btn btn-sm btn-primary" type="submit">${icon("brain")}写入 PowerContext</button></form>
        </div>
      </aside>
    </div>
  </section>`;
}

// ------------------------------------------------------------------ drawer / paper
async function openPaper(paperId) {
  try {
    const paper = await api(`/api/papers/${paperId}`);
    state.paper = paper;
    state.paperTab = "read";
    state.paperDraft = {
      status: paper.status,
      takeaway: paper.reading_memory?.takeaway || "",
      noteContent: "",
      noteType: "takeaway",
      ...Object.fromEntries(Object.keys(FIELD_LABEL).map((key) => [key, paper[`review_${key}`] || ""])),
    };
    renderDrawer();
    document.body.style.overflow = "hidden";
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderDrawer() {
  const paper = state.paper;
  if (!paper) return;
  const draft = state.paperDraft;
  const tabs = [
    ["read", "导读", ""],
    ["evidence", `证据片段`, paper.chunks?.length || 0],
    ["notes", "精读笔记", paper.notes?.length || 0],
    ["review", "综述字段", Object.keys(FIELD_LABEL).filter((key) => String(draft[key] || "").length >= 6).length],
  ];
  const tabsHtml = tabs.map(([key, label, count]) => `<button class="drawer-tab ${state.paperTab === key ? "active" : ""}" type="button" data-action="drawer-tab" data-tab="${key}">${label}${count !== "" ? ` <span class="muted">${count}</span>` : ""}</button>`).join("");
  let body = "";
  if (state.paperTab === "read") {
    body = `<div class="drawer-section"><h4>中文导读</h4><p class="abstract-text">${escapeHtml(paper.abstract)}</p></div>
      <div class="drawer-section"><h4>出处</h4><div class="cite-box"><strong>${escapeHtml(paper.title)}</strong>${escapeHtml(paper.cite_text || paper.authors)}${paper.doi ? `<br>DOI: ${escapeHtml(paper.doi)}` : ""}</div></div>
      <div class="drawer-section"><h4>作者与发表</h4><div class="profile-grid"><div class="profile-field"><span>作者</span><strong>${escapeHtml(paper.authors || "—")}</strong></div><div class="profile-field"><span>发表</span><strong>${escapeHtml(paper.venue || "—")} · ${escapeHtml(paper.year || "")}</strong></div><div class="profile-field"><span>类型</span><strong>${paper.source_type === "note" ? "研究笔记 / 内部资料" : "论文"}</strong></div><div class="profile-field"><span>标签</span><strong>${escapeHtml((paper.tags || []).join(" · ") || "—")}</strong></div></div></div>
      ${paper.reading_memory ? `<div class="drawer-section"><h4>来自研究记忆</h4><div class="note-card"><span class="note-type">${escapeHtml(STATUS_LABEL[paper.reading_memory.status] || "")} · ${relativeTime(paper.reading_memory.saved_at)}</span><p>${escapeHtml(paper.reading_memory.takeaway || "已记录阅读状态，尚未写一句话结论。")}</p><time>${escapeHtml(paper.reading_memory.artifact_id || "")}</time></div></div>` : ""}`;
  } else if (state.paperTab === "evidence") {
    body = `<div class="drawer-section"><h4>seekdb 中的证据片段</h4>${(paper.chunks || []).map((chunk) => `<div class="chunk-card"><div class="chunk-top"><span class="chunk-section">${escapeHtml(chunk.section)}</span><span class="chunk-page">${escapeHtml(chunk.page || "")}</span></div><p>${escapeHtml(chunk.content)}</p></div>`).join("")}</div>`;
  } else if (state.paperTab === "notes") {
    body = `<div class="drawer-section"><h4>已有笔记</h4>${(paper.notes || []).map((note) => `<div class="note-card"><span class="note-type">${escapeHtml(note.note_type)}</span><p>${escapeHtml(note.content)}</p><time>${formatDate(note.created_at, true)}</time></div>`).join("") || '<p class="muted tiny">还没有笔记。读到关键处，留一句能让自己下次看懂的话。</p>'}</div>
      <div class="drawer-section"><h4>写一条笔记</h4><form id="note-form"><div class="field-row"><div class="field"><label>类型</label><select class="select" id="note-type"><option value="takeaway">结论</option><option value="method">方法</option><option value="quote">摘录</option><option value="question">问题</option><option value="idea">想法</option></select></div><div class="field"><label>会同步</label><input class="input" value="seekdb + PowerContext" disabled></div></div><div class="field mt-8"><label>内容</label><textarea class="textarea" id="note-content" placeholder="例如：延迟后测是必须保留的终点，练习成绩不能替代。">${escapeHtml(draft.noteContent || "")}</textarea></div><button class="btn btn-sm btn-primary mt-8" type="submit">${icon("plus")}保存笔记</button></form></div>`;
  } else {
    body = `<div class="drawer-section"><h4>综述字段</h4><div class="review-fields">${Object.entries(FIELD_LABEL).map(([key, label]) => `<div class="field"><label>${label}<span class="tiny muted">${String(draft[key] || "").length}/600</span></label><textarea class="textarea" data-draft-field="${key}" maxlength="600">${escapeHtml(draft[key] || "")}</textarea></div>`).join("")}</div><div class="drawer-actions mt-14"><button class="btn btn-primary" type="button" data-action="save-review-fields">${icon("check")}保存到 seekdb</button><span class="tiny muted">保存后会进入综述矩阵与草稿。</span></div></div>`;
  }
  $("#drawer-root").innerHTML = `<div class="drawer-scrim" data-action="close-drawer"></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="资料详情">
    <div class="drawer-head">
      <div class="drawer-head-top"><span class="drawer-kicker">${escapeHtml(paper.venue || "RESEARCH RECORD")} · ${escapeHtml(paper.year || "")}</span><button class="drawer-close" type="button" data-action="close-drawer" aria-label="关闭">${icon("x")}</button></div>
      <h2 class="drawer-title">${escapeHtml(paper.title)}</h2>
      <p class="drawer-sub">${escapeHtml(paper.authors || "")}</p>
      <div class="drawer-tools">${statusPill(paper.status)}<div class="status-switch">${["to_read", "reading", "read"].map((status) => `<button type="button" class="${paper.status === status ? "active" : ""}" data-action="set-paper-status" data-status="${status}">${STATUS_LABEL[status]}</button>`).join("")}</div>${paper.doi ? `<a class="btn btn-sm btn-ghost" href="${escapeAttr(paper.doi.startsWith("http") ? paper.doi : `https://doi.org/${paper.doi}`)}" target="_blank" rel="noreferrer">${icon("external")}DOI</a>` : ""}<button class="btn btn-sm btn-ghost" type="button" data-action="export-bibtex" data-paper-id="${escapeAttr(paper.paper_id)}">${icon("download")}导出 BibTeX</button></div>
    </div>
    <div class="drawer-tabs">${tabsHtml}</div>
    <div class="drawer-body">${body}</div>
  </aside>`;
}

function closeDrawer() {
  $("#drawer-root").innerHTML = "";
  state.paper = null;
  state.paperDraft = null;
  document.body.style.overflow = "";
}

// ------------------------------------------------------------------ profile / modals
function openProfile() {
  const profile = state.memory?.profile || state.bootstrap?.profile || {};
  $("#modal-root").innerHTML = `<div class="modal-scrim" data-action="close-modal"></div><section class="modal" role="dialog" aria-modal="true" aria-label="编辑研究画像">
    <div class="modal-head"><div><h3>研究画像</h3><p>每次保存都会写入 PowerContext，并改变下一次检索的排序。</p></div><button class="drawer-close" type="button" data-action="close-modal">${icon("x")}</button></div>
    <form class="modal-body" id="profile-form">
      <div class="field-row"><div class="field"><label>称呼</label><input class="input" name="name" value="${escapeAttr(profile.name || "")}" placeholder="研究者"></div><div class="field"><label>领域</label><input class="input" name="field" value="${escapeAttr(profile.field || "")}" placeholder="教育技术学"></div></div>
      <div class="field-row"><div class="field"><label>研究阶段</label><input class="input" name="stage" value="${escapeAttr(profile.stage || "")}" placeholder="文献综述"></div><div class="field"><label>方法偏好（逗号分隔）</label><input class="input" name="methods" value="${escapeAttr((profile.methods || []).join(", "))}" placeholder="随机对照实验, 混合方法"></div></div>
      <div class="field"><label>当前目标</label><input class="input" name="goal" value="${escapeAttr(profile.goal || "")}" placeholder="3 周内完成开题综述"></div>
      <div class="field"><label>核心研究问题</label><textarea class="textarea" name="question" style="min-height:62px" placeholder="生成式 AI 如何影响初学者的学习迁移？">${escapeHtml(profile.question || "")}</textarea></div>
      <div class="field"><label>关注主题（逗号分隔）</label><input class="input" name="focus_tags" value="${escapeAttr((profile.focus_tags || []).join(", "))}" placeholder="生成式AI, 编程教育, 学习迁移"></div>
      <div class="field"><label>写作偏好（逗号分隔）</label><input class="input" name="preferences" value="${escapeAttr((profile.preferences || []).join(", "))}" placeholder="先看方法与局限, 中文笔记"></div>
      <div class="modal-actions"><button class="btn" type="button" data-action="close-modal">取消</button><button class="btn btn-primary" type="submit">${icon("check")}保存并写入记忆</button></div>
    </form>
  </section>`;
}

function openTrace() {
  const result = state.search;
  if (!result) { toast("先做一次检索", "error"); return; }
  const trace = (result.trace || []).map((item) => `<div class="trace-card"><div class="trace-card-head">${escapeHtml(item.label)}<span>${item.rows} rows · ${item.elapsed_ms} ms</span></div><pre class="trace-sql">${escapeHtml(item.sql)}</pre><div class="trace-params">params: ${escapeHtml((item.params || []).join(" | "))}</div></div>`).join("");
  const memory = result.memory || {};
  $("#modal-root").innerHTML = `<div class="modal-scrim" data-action="close-modal"></div><section class="modal" style="width:min(780px,94vw)" role="dialog" aria-modal="true" aria-label="检索轨迹">
    <div class="modal-head"><div><h3>这次检索的 SQL 轨迹</h3><p>不是一句“已检索”。这是 seekdb 实际执行的语句、候选数与耗时。</p></div><button class="drawer-close" type="button" data-action="close-modal">${icon("x")}</button></div>
    <div class="modal-body">
      <div class="trace-summary"><div class="trace-stat"><strong>${result.counts.vector_candidates}</strong><span>向量候选</span></div><div class="trace-stat"><strong>${result.counts.text_candidates}</strong><span>全文候选</span></div><div class="trace-stat"><strong>${result.counts.fused_chunks}</strong><span>融合片段</span></div><div class="trace-stat"><strong>${result.latency_ms}ms</strong><span>总耗时</span></div></div>
      <div class="trace-grid">${trace}</div>
      <p class="trace-note">融合权重：语义 44% + 全文 31% + 主题重合 15% + 阅读状态 10%。记忆只作用于主题与状态加权；片段始终来自 seekdb 原文。Embedding：${escapeHtml(result.embedding?.provider || "")} · ${escapeHtml(result.embedding?.dimension || "")} 维。</p>
      <div class="cite-box mt-14"><strong>本次记忆上下文</strong>${escapeHtml(memory.summary || "未连接")} · 关注 ${escapeHtml((memory.focus_tags || []).join("、") || "—")}</div>
    </div>
  </section>`;
}

function closeModal() {
  $("#modal-root").innerHTML = "";
  document.body.style.overflow = state.paper ? "hidden" : "";
}

// ------------------------------------------------------------------ shell helpers
function ensureSearchShell() {
  // Kept for symmetry: views replace #view directly.
}

function openSidebar() {
  $("#sidebar").classList.add("open");
  $("#mobile-scrim").classList.add("open");
}
function closeSidebar() {
  $("#sidebar").classList.remove("open");
  $("#mobile-scrim").classList.remove("open");
}

function copyText(text, message = "已复制") {
  if (!text) { toast("没有可复制的内容", "error"); return; }
  navigator.clipboard?.writeText(text).then(() => toast(message)).catch(() => toast("复制失败，请手动选择", "error"));
}

// ------------------------------------------------------------------ events
function bindEvents() {
  document.addEventListener("click", async (event) => {
    const routeEl = event.target.closest("[data-route]");
    if (routeEl) {
      event.preventDefault();
      navigate(routeEl.dataset.route);
      return;
    }
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    if (action === "open-sidebar") return openSidebar();
    if (action === "close-sidebar") return closeSidebar();
    if (action === "nav") return navigate(target.dataset.route);
    if (action === "focus-search") {
      if (location.hash !== "#/search") { state.focusSearch = true; navigate("search"); }
      else { $("#search-input")?.focus(); }
      return;
    }
    if (action === "retry-boot") return init();
    if (action === "open-paper") return openPaper(target.dataset.paperId);
    if (action === "close-drawer") return closeDrawer();
    if (action === "drawer-tab") { state.paperTab = target.dataset.tab; renderDrawer(); return; }
    if (action === "run-example") return doSearch(target.dataset.query);
    if (action === "search-tag") { state.filters.tags = [target.dataset.tag]; state.filtersPanel = true; navigate("search"); return; }
    if (action === "filter-tag") {
      const tag = target.dataset.tag;
      state.filters.tags = state.filters.tags.includes(tag) ? state.filters.tags.filter((item) => item !== tag) : [...state.filters.tags, tag];
      renderSearch();
      return;
    }
    if (action === "toggle-filter-panel") { state.filtersPanel = !state.filtersPanel; renderSearch(); return; }
    if (action === "clear-filters") { state.filters = { tags: [], status: "all", year_min: "", year_max: "", source_type: "all" }; renderSearch(); return; }
    if (action === "apply-filters") {
      state.filters.status = $("#filter-status")?.value || "all";
      state.filters.year_min = $("#filter-year-min")?.value || "";
      state.filters.year_max = $("#filter-year-max")?.value || "";
      state.filters.source_type = $("#filter-type")?.value || "all";
      state.filtersPanel = false;
      if (state.query) doSearch(state.query); else renderSearch();
      return;
    }
    if (action === "open-trace") return openTrace();
    if (action === "search-memory") {
      const query = target.dataset.query || state.query;
      try {
        const data = await api(`/api/memory/search?q=${encodeURIComponent(query)}`);
        const items = data.items || [];
        toast(items.length ? `PowerContext 召回 ${items.length} 条相关记忆` : "PowerContext 里没有相关记忆");
      } catch (error) { toast(error.message, "error"); }
      return;
    }
    if (action === "add-to-review") {
      state.reviewSelected.add(target.dataset.paperId);
      state.librarySelected.add(target.dataset.paperId);
      toast("已加入综述选择，去「综述矩阵」生成");
      return;
    }
    if (action === "toggle-select") {
      const id = target.dataset.paperId;
      if (state.librarySelected.has(id)) state.librarySelected.delete(id); else state.librarySelected.add(id);
      renderLibraryGrid();
      return;
    }
    if (action === "clear-library-selection") { state.librarySelected.clear(); renderLibraryGrid(); return; }
    if (action === "selected-to-review") { state.reviewSelected = new Set(state.librarySelected); navigate("review"); return; }
    if (action === "library-status") { state.library.status = target.dataset.status; await loadLibraryPapers(); return; }
    if (action === "select-all-review") {
      state.reviewSelected = new Set(state.reviewPapers.map((paper) => paper.paper_id));
      renderReview();
      return;
    }
    if (action === "toggle-review-paper") {
      const id = target.dataset.paperId;
      if (state.reviewSelected.has(id)) state.reviewSelected.delete(id); else state.reviewSelected.add(id);
      renderReview();
      return;
    }
    if (action === "generate-review") return generateReview();
    if (action === "toggle-matrix-edit") {
      state.matrixEditing = !state.matrixEditing;
      if (state.review) renderReview();
      if (state.matrixEditing) toast("单元格已可编辑，失焦自动保存");
      return;
    }
    if (action === "export-review") return exportReview();
    if (action === "copy-draft") return copyText(state.review?.draft?.markdown || "", "综述草稿已复制");
    if (action === "save-review-memory") return saveReviewMemory();
    if (action === "open-profile") return openProfile();
    if (action === "close-modal") return closeModal();
    if (action === "refresh-memory") { state.memory = await api("/api/memory"); renderMemory(); toast("记忆已刷新"); return; }
    if (action === "open-pc") { window.open(state.memory?.health?.url || "http://127.0.0.1:8765", "_blank", "noopener"); return; }
    if (action === "toggle-matrix-edit") return;
    if (action === "set-paper-status") {
      const status = target.dataset.status;
      return savePaperStatus(status);
    }
    if (action === "export-bibtex") {
      return exportBibtex(target.dataset.paperId);
    }
    if (action === "save-review-fields") return saveReviewFields();
    if (action === "save-memory-memory") {
      $("#memory-note-text")?.focus();
      return;
    }
  });

  document.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    if (form.id === "search-form") {
      const query = new FormData(form).get("query") || $("#search-input")?.value;
      return doSearch(query);
    }
    if (form.id === "recall-form") {
      const query = $("#recall-query")?.value.trim();
      if (!query) return;
      const root = $("#recall-results");
      root.innerHTML = `<div class="recall-hit"><span class="spinner"></span> 正在召回…</div>`;
      try {
        const data = await api(`/api/memory/search?q=${encodeURIComponent(query)}`);
        const items = data.items || [];
        root.innerHTML = items.length ? items.map((item) => `<div class="recall-hit"><b>${escapeHtml(item.kind || "memory")} · ${escapeHtml(item.matched_by || "match")}</b><br>${escapeHtml((item.summary || item.text || "").slice(0, 160))}</div>`).join("") : `<div class="recall-hit">没有召回结果。换一个更接近你已保存判断的说法。</div>`;
      } catch (error) {
        root.innerHTML = `<div class="recall-hit">${escapeHtml(error.message)}</div>`;
      }
      return;
    }
    if (form.id === "memory-note-form") {
      const text = $("#memory-note-text")?.value.trim();
      if (!text) { toast("先写一条判断", "error"); return; }
      try {
        await api("/api/memory/note", { method: "POST", body: JSON.stringify({ text, kind: "research_note" }) });
        $("#memory-note-text").value = "";
        state.memory = await api("/api/memory");
        renderMemory();
        toast("已写入 PowerContext，下一次检索会读到它");
      } catch (error) { toast(error.message, "error"); }
      return;
    }
    if (form.id === "note-form") {
      const content = $("#note-content")?.value.trim();
      if (!content) { toast("先写点内容", "error"); return; }
      try {
        await api("/api/notes", { method: "POST", body: JSON.stringify({ paper_id: state.paper.paper_id, note_type: $("#note-type")?.value || "note", content }) });
        const paper = await api(`/api/papers/${state.paper.paper_id}`);
        state.paper = paper;
        state.paperDraft.noteContent = "";
        renderDrawer();
        toast("笔记已写入 seekdb 与研究记忆");
      } catch (error) { toast(error.message, "error"); }
      return;
    }
    if (form.id === "profile-form") {
      const payload = Object.fromEntries(new FormData(form).entries());
      payload.methods = String(payload.methods || "").split(/[,，]/).map((item) => item.trim()).filter(Boolean);
      payload.preferences = String(payload.preferences || "").split(/[,，]/).map((item) => item.trim()).filter(Boolean);
      payload.focus_tags = String(payload.focus_tags || "").split(/[,，]/).map((item) => item.trim()).filter(Boolean);
      try {
        await api("/api/memory/profile", { method: "POST", body: JSON.stringify(payload) });
        closeModal();
        await refreshBootstrap();
        state.memory = await api("/api/memory");
        if (location.hash === "#/memory") renderMemory(); else renderToday();
        toast("研究画像已保存，并写入 PowerContext");
      } catch (error) { toast(error.message, "error"); }
      return;
    }
  });

  document.addEventListener("input", (event) => {
    const field = event.target.dataset.draftField;
    if (field && state.paperDraft) state.paperDraft[field] = event.target.value;
    if (event.target.id === "review-question") state.reviewQuestion = event.target.value;
    if (event.target.id === "library-q") {
      state.library.q = event.target.value;
      window.clearTimeout(state.libraryTimer);
      state.libraryTimer = window.setTimeout(() => loadLibraryPapers().catch((error) => toast(error.message, "error")), 320);
    }
    if (event.target.id === "note-content" && state.paperDraft) state.paperDraft.noteContent = event.target.value;
  });

  document.addEventListener("change", (event) => {
    if (event.target.dataset.filter) {
      state.filters[event.target.dataset.filter] = event.target.value;
    }
    if (event.target.id === "library-tag") {
      state.library.tag = event.target.value;
      loadLibraryPapers().catch((error) => toast(error.message, "error"));
    }
  });

  document.addEventListener("focusout", async (event) => {
    const cell = event.target.closest(".matrix-cell[contenteditable='true']");
    if (!cell || !state.review) return;
    const paperId = cell.dataset.paperId;
    const field = cell.dataset.field;
    const value = cell.innerText.trim() === "待补充" ? "" : cell.innerText.trim();
    try {
      await api(`/api/papers/${paperId}`, { method: "PATCH", body: JSON.stringify({ [`review_${field}`]: value }) });
      const row = state.review?.matrix?.rows?.find((item) => item.paper_id === paperId);
      if (row) row.cells[field] = value;
      toast("单元格已保存；重新生成可同步草稿与覆盖度");
    } catch (error) { toast(error.message, "error"); }
  });

  window.addEventListener("hashchange", () => routeFromHash().catch((error) => toast(error.message, "error")));
  // Exposed for local acceptance scripts and browser-console debugging.
window.__yanmai = state;

window.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      state.focusSearch = true;
      if (location.hash !== "#/search") navigate("search"); else { $("#search-input")?.focus(); state.focusSearch = false; }
    }
    if (event.key === "Escape") {
      if ($("#modal-root")?.innerHTML) closeModal();
      else if ($("#drawer-root")?.innerHTML) closeDrawer();
      else closeSidebar();
    }
  });
}

async function savePaperStatus(status) {
  if (!state.paper) return;
  try {
    const result = await api(`/api/papers/${state.paper.paper_id}`, { method: "PATCH", body: JSON.stringify({ status, takeaway: state.paperDraft?.takeaway || "" }) });
    state.paper = { ...state.paper, ...result.paper, reading_memory: result.memory?.data || state.paper.reading_memory };
    state.paperDraft.status = status;
    renderDrawer();
    if (state.bootstrap) await refreshBootstrap();
    toast(`已标记为「${STATUS_LABEL[status]}」，进度写入研究记忆`);
  } catch (error) { toast(error.message, "error"); }
}

async function saveReviewFields() {
  if (!state.paper) return;
  const payload = {};
  for (const key of Object.keys(FIELD_LABEL)) payload[`review_${key}`] = state.paperDraft[key] || "";
  try {
    const result = await api(`/api/papers/${state.paper.paper_id}`, { method: "PATCH", body: JSON.stringify(payload) });
    state.paper = { ...state.paper, ...result.paper };
    renderDrawer();
    toast("综述字段已保存，矩阵会使用新内容");
  } catch (error) { toast(error.message, "error"); }
}

async function generateReview() {
  if (!state.reviewSelected.size) { toast("先选至少一篇文献", "error"); return; }
  const question = state.reviewQuestion || state.bootstrap?.profile?.question || "";
  try {
    const result = await api("/api/review/matrix", {
      method: "POST",
      body: JSON.stringify({ paper_ids: [...state.reviewSelected], question, remember: true, note: "从综述矩阵页面生成" }),
    });
    state.review = result;
    state.matrixEditing = false;
    renderReview();
    if (state.bootstrap) await refreshBootstrap();
    toast(`矩阵已生成：${result.matrix.paper_count} 篇，覆盖度 ${result.matrix.coverage}%`);
  } catch (error) { toast(error.message, "error"); }
}

async function saveReviewMemory() {
  if (!state.reviewSelected.size) { toast("先选文献", "error"); return; }
  try {
    const result = await api("/api/review/matrix", {
      method: "POST",
      body: JSON.stringify({ paper_ids: [...state.reviewSelected], question: state.reviewQuestion, remember: true, note: "手动保存综述决策" }),
    });
    state.review = result;
    toast("综述决策已写入 PowerContext");
    state.memory = await api("/api/memory");
  } catch (error) { toast(error.message, "error"); }
}

async function exportBibtex(paperId) {
  try {
    const response = await fetch(`/api/papers/${paperId}/bibtex`);
    if (!response.ok) throw new Error("导出失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${paperId}.bib`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    toast("BibTeX 已下载");
  } catch (error) { toast(error.message, "error"); }
}

async function exportReview() {
  if (!state.reviewSelected.size) { toast("先选文献", "error"); return; }
  try {
    const response = await fetch("/api/review/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_ids: [...state.reviewSelected], question: state.reviewQuestion }),
    });
    if (!response.ok) throw new Error("导出失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "yanmai-review-draft.md";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    toast("Markdown 已下载");
  } catch (error) { toast(error.message, "error"); }
}

init();
