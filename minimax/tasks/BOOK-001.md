---
task_id: BOOK-001
title: 为 BookNest 商品搜索增加价格区间筛选
keywords: [price, filter, search, api, regression]
target_symbols: [booknest.service.search_products, booknest.api.ProductRequestHandler]
must_preserve: [category filter, keyword filter, sort order, limit validation]
---

# 任务 BOOK-001

## 要改什么

为 `booknest.service.search_products` 增加 `min_price` / `max_price` 两个可选
参数，按闭区间过滤商品；在 `GET /api/products` 暴露同名查询参数，非法价格
或倒置区间返回 HTTP 400。

## 必须保持什么

1. 分类筛选仍大小写不敏感，关键词仍匹配标题/分类/标签。
2. `price_asc`、`price_desc`、`rating_desc` 的既有排序不变。
3. 不传价格参数时，结果与改动前逐项一致。
4. `limit` 仍校验 1..100，`/health` 仍返回 200。

## 验收命令

```bash
python -m pytest -q
```
