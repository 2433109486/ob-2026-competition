# Qoder 交接：从导入到 Qoder Sites 公开

> 目标：让本目录成为**可核对的 Qoder 开发作品**，并把 `site/` 发布成「任何人都可访问」的项目网站。
> 本仓库已完成代码、测试、截图和站点素材；你只需要在 Qoder 中登录、重放关键任务、截图、发布。

## 0. 前置

- Qoder 个人账号（不要用企业版发布公开站点；企业版无法设公开访问）。
- Qoder 桌面端 / IDE / CLI 任一；推荐 CLI，便于把对话记录留在终端。
- 本机已能运行 seekdb 2881、PowerContext 8765、研脉 7860（见 [`RUNBOOK.md`](RUNBOOK.md)）。

## 1. 安装并登录 Qoder CLI（可选）

```powershell
# Windows PowerShell
irm https://qoder.com/install.ps1 | iex

# 或 npm（需要 Node >= 20）
npm install -g @qoder-ai/qodercli

qoder --version
```

在 `qoder/` 目录运行：

```powershell
cd qoder
qoder
```

首次进入会在 TUI 里提示登录；输入 `/login`，选：

1. **Login with Qoder Platform (Browser)**：浏览器登录（推荐）；
2. 或 **Use Qoder Personal Access Token**：在 <https://qoder.com/account/integrations> 生成 PAT，
   设置 `QODER_PERSONAL_ACCESS_TOKEN`。**不要把 PAT 写进仓库或截图。**

登录后输入 `/status`，截图 Usage/Status；账号 UID 在 **Settings → Profile → Edit** 查看并记录。

> 如果浏览器没有自动打开，CLI 会打印登录 URL，手动复制到浏览器即可。

## 2. 导入仓库

赛题要求：基于 `https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem`
导入私有 repo 后，在**同名分支**上开发，资产放入 `qoder/`。

```powershell
git clone <你的私有仓库地址>
cd <repo>
git checkout 2026-competition-ecosystem   # 或导入后生成的同名分支
# 确认 qoder/ 下是本项目
```

如果还没克隆：

```powershell
git clone https://github.com/2433109486/ob-2026-competition.git
cd ob-2026-competition
git checkout submission-2026
```

> 提交时记录分支名与 commit hash；本项目的资产全部在 `qoder/` 子目录，避免影响其他赛道目录。

## 3. 在 Qoder 中重放开发任务

打开 Qoder，项目根目录选仓库根（不是 `qoder/`），在对话中说明“只改 `qoder/` 目录”。
依次发送 [`QODER_DEVLOG.md`](QODER_DEVLOG.md) 第 2 节的 7 个任务。

建议每次任务后：

1. 让 Qoder 运行对应验收命令；
2. 截图对话 + 终端输出；
3. 用下面的命名保存到 `docs/qoder-evidence/`。

| 截图 | 内容 | 建议画面 |
| --- | --- | --- |
| `01-requirements.png` | 需求拆解/计划 | Qoder 输出计划 + 你确认的回复 |
| `02-seekdb-schema.png` | 建表/导入 | Qoder 终端 `init_db.py` 输出 papers=10/chunks=34 |
| `03-hybrid-search.png` | 检索实现 | Qoder 对话 + `/api/search` 的 trace |
| `04-powercontext.png` | 记忆读写 | Qoder 对话 + 时间线/entries 结果 |
| `05-ui.png` | 前端页面 | Qoder 预览或浏览器截图 |
| `06-debug.png` | 修 bug | 报错 → 定位 → 修复 → 复跑 |
| `07-acceptance.png` | 自动验收 | `PASS: 23 checks` |
| `08-sites.png` | 站点发布 | Qoder Sites 发布成功 + 公开访问设置 |
| `09-bibtex.png` | Qoder 实际增量 | BibTeX 代码/测试 + `PASS 23 checks` |

> 只截“成功页面”不够。最好保留一次真实失败与修复（例如 PowerContext 422），
> 让评审看到 Qoder 参与了调试，而不是只参与生成。

## 4. 运行并确认基线

在 Qoder 的终端里：

```powershell
cd qoder
.\.venv\Scripts\python.exe scripts\check_env.py
.\.venv\Scripts\python.exe scripts\init_db.py --reset
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7860
```

另开终端：

```powershell
.\.venv\Scripts\python.exe scripts\acceptance.py
python scripts\e2e_ui.py
```

确认 23 项验收与浏览器路径通过，再进入发布。

## 5. 用 Qoder Sites 发布 `site/`

### 5.1 交互式（推荐）

在 Qoder 会话里输入：

```text
@sites 把 qoder/site 目录发布成一个静态网站，名称是「研脉 ResearchPulse」。
要求：
- 首页包含项目简介、真实痛点、核心功能、演示视频/截图、技术架构、代码仓库链接、运行说明入口；
- 使用 site/assets 下已有的截图和 demo 视频；
- 先预览，不要直接发布；
- 预览确认后发布，并把可见范围设为「任何人都可访问」。
```

Qoder 会先给预览。检查：

- [ ] 首屏标题、截图、视频都能加载（不要出现裂图）；
- [ ] “代码仓库”链接可点；
- [ ] “运行说明”链接/段落可读；
- [ ] 移动端不横向溢出；
- [ ] 没有占位符 `<YOUR_REPO_URL>`、`<QODER_UID>` 等未替换文本。

确认后点 **Publish**，在 Share / Access 里选择 **Anyone can access**（个人账号会二次确认
“Allow public access”）。

### 5.2 CLI（可选）

```powershell
qoder sites list
qoder sites operations
qoder sites describe prepare_site
```

发布/改权限属于写操作，建议在交互式会话里让 Sites Skill 处理确认与幂等；
不要手写 `publish_site` 绕过确认。

### 5.3 发布后

1. 复制站点 URL；
2. **无痕窗口**打开，确认未登录也能访问；
3. 在 Qoder Sites 的「访问统计」截一张图（后续可补充真实访问数据）；
4. 把 URL 写入：
   - `docs/QODER_DEVLOG.md` 顶部；
   - `site/index.html` 中的代码仓库/体验入口（如有）；
   - 提交平台的“项目网站网址”。

> Qoder Sites 修改内容后需要再次点「发布」才会更新线上版本；评审结束前不要暂停/删除站点。

## 6. 提交材料对照

| 赛题要求 | 本仓库对应 |
| --- | --- |
| 项目网站 URL | Qoder Sites 发布后填写 |
| 代码仓库 | 私有仓库向评审开放，或公开仓库 |
| 运行说明 | [`RUNBOOK.md`](RUNBOOK.md) |
| 验证样例 | [`VALIDATION.md`](VALIDATION.md) + `docs/evidence/` |
| Qoder 开发记录 | [`QODER_DEVLOG.md`](QODER_DEVLOG.md) + `docs/qoder-evidence/` 截图 + UID |
| 使用 seekdb | `app/db.py`、`app/retrieval.py`、`docs/TECH_USAGE.md` |
| 使用 PowerContext | `app/memory.py`、`docs/TECH_USAGE.md` |
| 项目网站 | `site/`（已可直接发布） |
| 使用效果（鼓励） | `docs/evidence/acceptance.json`、`/api/stats`；外部用户数据待补 |

## 7. 不要提交

- `.env`、`.env.powercontext`、`runtime/`、任何真实 API Key / PAT / 密码；
- `docs/qoder-evidence/` 中出现 token、邮箱、手机号的截图（打码）；
- `site/` 中的本地绝对路径（发布前全局搜索 `D:\` / `/mnt/` / `127.0.0.1` 的说明性内容可保留）。

## 8. 常见问题

| 现象 | 处理 |
| --- | --- |
| `qoder` 登录打不开浏览器 | 复制终端打印的 URL 到浏览器；或设置 PAT |
| Sites 发布后无法公开 | 确认是个人账号；企业版不支持公开访问 |
| `site/` 图片裂开 | 确认 `site/assets/` 已包含截图/视频，路径为相对路径 |
| 评审打开站点看不到演示 | 站点是静态展示；完整交互需按 RUNBOOK 本地启动 |
| Qoder 修改后线上没变 | 重新点 Publish；发布的是当前版本 |
| 截图被判定为伪造 | 保留 Qoder 对话、终端输出、时间戳与 UID；不要 P 图 |
