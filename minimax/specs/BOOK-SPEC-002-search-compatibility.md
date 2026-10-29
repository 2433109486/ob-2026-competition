---
id: BOOK-SPEC-002
title: 既有搜索行为兼容约束
version: 1
status: active
kind: spec
tags: [search, compatibility, regression, category, keyword, sort]
applies_to: [booknest.service.search_products, booknest.api.ProductRequestHandler]
supersedes:
---

# 既有搜索行为兼容约束（BOOK-SPEC-002）

这些行为在价格筛选上线后 MUST 保持不变，属于回归验证范围。

## REQ-001 分类筛选

`category` MUST 大小写不敏感地精确匹配商品分类。

## REQ-002 关键词筛选

`keyword` MUST 在标题、分类和标签中做大小写不敏感的子串匹配。

## REQ-003 排序与数量

`price_asc`、`price_desc`、`rating_desc` MUST 保持原有排序；`limit` MUST
维持在 1 到 100 之间，越界时抛出 `ValueError`。

## REQ-004 无价格参数时结果不变

不传 `min_price` / `max_price` 时，搜索结果 MUST 与改动前逐项一致。
