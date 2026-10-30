# 提交清单（2026 Qoder 赛题）

## 已完成

- [x] 可运行项目：FastAPI + 原生 SPA + seekdb 1.4 + PowerContext 1.4.1
- [x] seekdb 实际检索：`VECTOR(768)` + HNSW、`ngram2` 全文、两路召回融合
- [x] PowerContext 实际记忆：Scope + Atomic Memory（画像/阅读进度/综述决策/研究判断）
- [x] 10 份演示资料、34 个证据片段、6 维综述矩阵、带引用 Markdown 草稿
- [x] 自动验收 23/23；pytest 12/12；浏览器路径 5 条无 console error
- [x] Qoder CN 实际新增单篇 BibTeX 导出（后端 / 前端 / 测试 / 验收）
- [x] 运行说明 `docs/RUNBOOK.md`
- [x] 验证样例 `docs/VALIDATION.md`
- [x] 技术证据 `docs/TECH_USAGE.md` + `docs/evidence/`
- [x] 真实截图 12 张 + 35 秒录屏 `docs/demo/demo.webm`
- [x] Qoder Sites 已发布，任何人可访问：<https://research-pulse-md400bulau4.qoder.zone/>
- [x] Qoder CN 真实会话截图已归档（status / prompt / read-docs / bibtex / sites）
- [x] Qoder UID、站点 URL 已写入 `docs/QODER_DEVLOG.md`
- [x] 代码已提交到 `qoder/` 目录

## 提交前核对

- [x] 无痕窗口访问站点成功（HTTP 200，图片/视频正常）
- [x] Qoder Sites 访问统计：4 次 / 3 独立访客（2026-10-30 10:59）
- [x] 未提交 `.env` / `runtime/` / 真实凭据
- [ ] 仓库已 push 到远端（本地 commit 需推送）
- [ ] 仓库已向评审开放访问

## 分支与提交

```text
repository: https://github.com/2433109486/ob-2026-competition
branch:     submission-2026
commit:     <见最终提交；运行 git log -1 --format=%H 获取>
asset dir:  qoder/
website:    https://research-pulse-md400bulau4.qoder.zone/
```

> 赛题基线为 `oceanbase/powercontext` 的 `2026-competition-ecosystem`。
> 导入私有 repo 后使用同名分支；本项目所有新增资产在 `qoder/`。

## 提交平台字段

| 字段 | 填什么 |
| --- | --- |
| 项目网站网址 | https://research-pulse-md400bulau4.qoder.zone/ |
| 代码仓库地址 | https://github.com/2433109486/ob-2026-competition（私有则邀请评审） |
| Qoder 账号 UID | 1473193271554286（Qoder CN 个人信息页） |
| 运行说明 | `qoder/docs/RUNBOOK.md` |
| 验证样例 | `qoder/docs/VALIDATION.md` |
| Qoder 开发记录 | `qoder/docs/qoder-evidence/` 截图 + UID |
| 使用效果（可选） | Qoder Sites 4 次访问 / 3 独立访客；`docs/evidence/usage.md` |

## 评审复现最短路径

```powershell
cd qoder
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# 先启动 seekdb 2881 与 PowerContext 8765
.\.venv\Scripts\python.exe scripts\check_env.py
.\.venv\Scripts\python.exe scripts\init_db.py --reset
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7860
# 打开 http://127.0.0.1:7860
```

## 不能提交

- `.env`、`.env.powercontext`、`runtime/`、任何 API Key / PAT / 密码
- 未脱敏的 Qoder 截图（token、邮箱、手机号）
- 未替换的 `<YOUR_REPO_URL>` / `<QODER_UID>` 占位符（站点中不能出现）
- 虚假的外部用户数据或提效对比

## 提交后自检

- [ ] 无痕窗口打开站点，未登录可访问
- [ ] 站点首屏、视频、5 张截图无裂图
- [ ] 仓库 `qoder/` 可克隆，`scripts/acceptance.py` 按 RUNBOOK 跑通
- [ ] `docs/evidence/acceptance.json` 与当前代码一致
- [ ] Qoder UID 与站点归属可对上
- [ ] 评审结束前不暂停/删除站点
