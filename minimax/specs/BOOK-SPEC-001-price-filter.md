---
id: BOOK-SPEC-001
title: 商品价格区间筛选
version: 2
status: active
kind: spec
tags: [price, filter, search, api, boundary]
applies_to: [booknest.service.search_products, booknest.api.ProductRequestHandler]
supersedes: BOOK-SPEC-001@1
---

# 商品价格区间筛选（BOOK-SPEC-001）

## REQ-001 区间上下界都包含

`search_products` MUST 接受可选参数 `min_price` 与 `max_price`，并按**闭区间**
过滤：`min_price <= product.price <= max_price`。

## REQ-002 只给一侧边界

只给 `min_price` 时 MUST 过滤掉更低价格的商品；只给 `max_price` 时 MUST
过滤掉更高价格的商品。两个参数都为空时结果 MUST 与引入该功能前完全一致。

## REQ-003 非法价格区间

`min_price` 或 `max_price` 为负数，或 `min_price > max_price` 时 MUST 抛出
`ValueError`，错误信息中 MUST 含 `min_price`。

## REQ-004 边界与空结果

`min_price == max_price` MUST 返回恰好等于该价格的商品；区间内没有商品时
MUST 返回空列表，不得抛出异常，也不得回退到未过滤结果。价格 `0` MUST 被当作
合法边界值，不得解释为“未设置”。

## REQ-005 过滤、排序、截断的顺序

实现 MUST 先按价格与既有条件过滤，再执行排序，最后应用 `limit`；不得先截断
再过滤，否则分页结果会漏掉命中项。
