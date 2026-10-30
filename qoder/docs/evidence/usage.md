# 使用效果材料（真实、可核对）

## 1. 项目网站

- URL: <https://research-pulse-md400bulau4.qoder.zone/>
- 发布方式：Qoder Sites
- 访问范围：任何人都可访问
- 无登录验证：2026-10-30 使用全新的 Playwright 浏览器上下文打开，HTTP 200，
  标题「研脉 ResearchPulse · 让文献综述有迹可循」，5 张图片和 1 个视频元素正常；
  截图见 `docs/screenshots/12-public-site.png`。
- 公开访问截图：`docs/qoder-evidence/08-sites.png`

## 2. Qoder Sites 访问统计

查询时间：2026-10-30 10:59:31（最近 7 天）

| 指标 | 数值 |
| --- | --- |
| 访问次数 | 4 |
| 独立访客 | 3 |
| 人均访问次数 | 1.33 |

来源：Qoder Sites → 研脉 ResearchPulse → 访问统计，截图
`docs/qoder-evidence/08-sites.png`。

> 样本非常小，且很可能包含开发者本人和评审预览，不能据此声称“外部用户提效”。
> 这里只记录真实站点访问，不伪造问卷、用户评价或提效比例。

## 3. 开发自测数据（不是外部用户）

| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 自动验收 | 23/23 | `docs/evidence/acceptance.json` |
| pytest | 12/12 | `docs/evidence/pytest.txt` |
| 演示资料 | 10 份 | `yanmai.papers` |
| 证据片段 | 34 个 | `yanmai.chunks` |
| 检索端到端耗时 | 约 170–240 ms | `search_log` / acceptance |
| 浏览器主路径 | 5 条通过，无 page console error | `scripts/e2e_ui.py` |

## 4. 后续可补充

如果邀请同学真实试用，建议记录：

- 试用人数与次数（Qoder Sites 访问统计 + 应用 `search_log`）；
- 一次完整综述流程的前后耗时（从检索到矩阵/草稿）；
- 经本人同意的匿名反馈；
- 根据反馈做出的至少一次迭代 commit。

不要把开发自测包装成外部使用效果。
