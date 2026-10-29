# 提交清单（2026 Qoder 赛题）

## 已完成

- [x] 可运行项目：FastAPI + 原生 SPA + seekdb 1.4 + PowerContext 1.4.1
- [x] seekdb 实际检索：`VECTOR(768)` + HNSW、`ngram2` 全文、两路召回融合
- [x] PowerContext 实际记忆：Scope + Atomic Memory（画像/阅读进度/综述决策/研究判断）
- [x] 10 份演示资料、34 个证据片段、6 维综述矩阵、带引用 Markdown 草稿
- [x] 自动验收 21/21；pytest 7/7；浏览器路径 5 条无 console error
- [x] 运行说明 `docs/RUNBOOK.md`
- [x] 验证样例 `docs/VALIDATION.md`
- [x] 技术证据 `docs/TECH_USAGE.md` + `docs/evidence/`
- [x] 真实截图 11 张 + 35 秒录屏 `docs/demo/demo.webm`
- [x] 项目网站 `site/`（静态，可直接发布）
- [x] 提交代码到 `qoder/` 目录

## 待完成（必须由 Qoder 账号本人操作）

- [ ] 在 Qoder 中登录个人账号（不要企业版）
- [ ] 按 `docs/QODER_DEVLOG.md` 第 2 节依次重放 7 个任务
- [ ] 把 Qoder 对话/终端截图放入 `docs/qoder-evidence/`（8 个命名，见该目录 README）
- [ ] 填写 Qoder 账号 UID 到 `docs/QODER_DEVLOG.md` 顶部
- [ ] 用 Qoder Sites 发布 `site/`，可见范围设为「任何人都可访问」
- [ ] 无痕窗口验证站点；记录 URL
- [ ] 把站点 URL 填入提交平台、`docs/QODER_DEVLOG.md`
- [ ] 记录最终分支/commit hash 到本页
- [ ] 清理 `.env` / `runtime/` / 真实凭据，确认仓库可被评审访问

## 分支与提交

```text
repository: https://github.com/2433109486/ob-2026-competition
branch:     submission-2026
commit:     96b04f45821e134da20f52cb8496bba00e6e7ed3
asset dir:  qoder/
```

> 赛题基线为 `oceanbase/powercontext` 的 `2026-competition-ecosystem`。
> 导入私有 repo 后使用同名分支；本项目所有新增资产在 `qoder/`。

## 提交平台字段

| 字段 | 填什么 |
| --- | --- |
| 项目网站网址 | Qoder Sites 发布后的完整 URL（无痕可打开） |
| 代码仓库地址 | 仓库 URL + 访问说明（私有则邀请评审） |
| Qoder 账号 UID | Qoder → Settings → Profile → Edit |
| 运行说明 | 上传 `docs/RUNBOOK.md` 或填仓库内路径 |
| 验证样例 | 上传 `docs/VALIDATION.md` 或填仓库内路径 |
| Qoder 开发记录 | `docs/qoder-evidence/` 截图 + UID |
| 使用效果（可选） | 当前只有开发自测，不伪造；可后续补访问统计 |

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
