# 研脉项目网站（Qoder Sites 发布目录）

这是 `site/` 静态站，不依赖构建步骤。Qoder Sites 发布时选择本目录即可。

## 内容

- 项目简介、真实痛点、核心功能
- 35 秒真实运行录屏（`assets/demo.webm`，WebM/VP8）
- 5 张真实界面截图 + 1 张移动端截图
- seekdb / PowerContext 技术证据（SQL 轨迹、Atomic Memory）
- 21 项自动验收结果
- 代码仓库、运行说明、验证样例入口
- 使用效果说明：当前为开发自测，未冒充外部用户数据

## 本地预览

```powershell
cd qoder
python -m http.server 7861 --bind 127.0.0.1 --directory site
# http://127.0.0.1:7861
```

## 发布前检查

- [ ] `assets/hero.png`、`assets/search.png`、`assets/review.png`、`assets/memory.png` 均能加载
- [ ] `assets/demo.webm` 可在浏览器播放（Chrome/Edge；Safari 可能不支持 VP8，保留海报图）
- [ ] 把 `index.html` 中仓库链接换成最终可访问地址
- [ ] 不包含本地绝对路径、Qoder UID、API Key
- [ ] 发布后在无痕窗口打开，确认「任何人都可访问」

## 替换素材

截图来自 `../docs/screenshots/`，视频来自 `../docs/demo/demo.webm`。
重新采集：

```powershell
python scripts/capture_ui.py
python scripts/record_demo.py
# 然后复制到 site/assets/
```

当前站点中的链接指向：

```text
https://github.com/2433109486/ob-2026-competition/tree/submission-2026/qoder
```

如果最终仓库地址不同，请全局替换。
