---
id: BOOK-SPEC-003
title: 商品查询 HTTP 接口行为
version: 1
status: active
kind: spec
tags: [api, http, price, filter, error]
applies_to: [booknest.api.ProductRequestHandler, booknest.api.create_server]
supersedes:
---

# 商品查询 HTTP 接口行为（BOOK-SPEC-003）

## REQ-001 查询参数

`GET /api/products` MUST 接受 `min_price` 与 `max_price` 查询参数，并把它们
传给 `search_products`。

## REQ-002 参数校验

`min_price` / `max_price` 不是数字、为负数或区间倒置时，接口 MUST 返回
HTTP 400，响应体 MUST 是含 `error` 字段的 JSON。

## REQ-003 成功响应

成功时 MUST 返回 HTTP 200，响应体为 `{"items": [...], "count": N}`；空结果
MUST 是 200 且 `count` 为 0。

## REQ-004 健康检查

`GET /health` MUST 返回 HTTP 200 与 `{"status": "ok"}`。
