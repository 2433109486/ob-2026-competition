---
id: BOOK-DEC-001
title: 价格边界与空结果决策
version: 1
status: active
kind: decision
tags: [price, boundary, decision, filter]
applies_to: [booknest.service.search_products]
supersedes:
---

# 价格边界与空结果决策（BOOK-DEC-001）

## DEC-001 闭区间

价格筛选采用闭区间，`max_price=99` 必须包含价格为 99 的商品。

## DEC-002 零价商品

`max_price=0` 是合法输入，必须能筛出价格为 0 的商品；不得把 0 当成“未设置”。

## DEC-003 空结果

没有命中商品是正常业务结果，服务返回空列表，HTTP 返回 200 与 `count=0`。
