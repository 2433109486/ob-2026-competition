"""DSL 静态校验：在导入 Dify 之前抓住最常见的低级错误。

检查项：
1. YAML 可解析，顶层字段齐全（kind/version/app/workflow/graph）；
2. 节点 id 唯一、边两端存在、存在唯一 start、所有节点从 start 可达；
3. `{{#node.var#}}` 变量引用都能找到前驱节点的输出；
4. Code 节点的 Python 能通过 `compile()`；
5. 不包含疑似真实凭据。

用法：python scripts/validate_dsl.py dsl/absurd-court.chatflow.yml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

VAR_RE = re.compile(r"\{\{#([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)#\}\}")
SYSTEM_VARS = {"sys.query", "sys.user_id", "sys.conversation_id", "sys.app_id", "sys.workflow_run_id", "sys.dialogue_count"}
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{16,}|api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9]{16,})", re.I)


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def collect_outputs(node: dict) -> set[str]:
    data = node.get("data") or {}
    node_type = data.get("type")
    if node_type == "start":
        return {v["variable"] for v in data.get("variables") or []}
    if node_type == "http-request":
        return {"body", "status_code", "headers", "files"}
    if node_type == "code":
        return set((data.get("outputs") or {}).keys())
    if node_type == "llm":
        return {"text", "usage", "finish_reason"}
    if node_type == "answer":
        return {"answer"}
    return set()


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "dsl/absurd-court.chatflow.yml")
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        fail("顶层不是对象")
    for key in ("kind", "version", "app", "workflow"):
        if key not in doc:
            fail(f"缺少顶层字段 {key}")
    if doc["kind"] != "app":
        fail("kind 必须是 app")
    if doc["app"].get("mode") not in ("advanced-chat", "workflow"):
        fail("app.mode 必须是 advanced-chat 或 workflow")
    graph = doc["workflow"].get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        fail("graph.nodes 为空")

    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        fail("节点 id 重复")
    starts = [n for n in nodes if (n.get("data") or {}).get("type") == "start"]
    if len(starts) != 1:
        fail(f"start 节点数量为 {len(starts)}")
    if starts[0]["id"] != "start":
        fail("start 节点 id 必须为 start")

    by_id = {n["id"]: n for n in nodes}
    for edge in edges:
        for end in ("source", "target"):
            if edge.get(end) not in by_id:
                fail(f"边 {edge.get('id')} 指向不存在的节点 {edge.get(end)}")

    # 可达性
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for edge in edges:
        adjacency[edge["source"]].append(edge["target"])
    seen = set()
    stack = ["start"]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, []))
    unreachable = set(ids) - seen
    if unreachable:
        fail(f"存在从 start 不可达的节点：{sorted(unreachable)}")

    # 变量引用：必须是前驱节点的输出
    predecessors: dict[str, set[str]] = {node_id: set() for node_id in ids}
    for edge in edges:
        predecessors[edge["target"]].add(edge["source"])

    def ancestors(node_id: str) -> set[str]:
        result, stack = set(), list(predecessors[node_id])
        while stack:
            item = stack.pop()
            if item in result:
                continue
            result.add(item)
            stack.extend(predecessors[item])
        return result

    for node in nodes:
        blob = yaml.safe_dump(node, allow_unicode=True)
        for ref_node, ref_var in VAR_RE.findall(blob):
            if f"{ref_node}.{ref_var}" in SYSTEM_VARS:
                continue
            if ref_node not in by_id:
                fail(f"节点 {node['id']} 引用了不存在的节点 {ref_node}")
            if ref_var not in collect_outputs(by_id[ref_node]):
                fail(f"节点 {node['id']} 引用了 {ref_node} 未声明的输出 {ref_var}")
            if ref_node not in ancestors(node["id"]):
                fail(f"节点 {node['id']} 引用了非前驱节点 {ref_node}")

    # Code 节点语法
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") == "code":
            try:
                compile(data.get("code", ""), f"<{node['id']}>", "exec")
            except SyntaxError as exc:
                fail(f"Code 节点 {node['id']} 语法错误：{exc}")

    # 凭据
    match = SECRET_RE.search(text)
    if match:
        fail(f"疑似真实凭据：{match.group(0)[:12]}...")

    llm_nodes = [n for n in nodes if (n.get("data") or {}).get("type") == "llm"]
    print(f"[OK] {path}")
    print(f"     nodes={len(nodes)} edges={len(edges)} llm={len(llm_nodes)} code={sum(1 for n in nodes if (n.get('data') or {}).get('type') == 'code')}")
    print(f"     model={llm_nodes[0]['data']['model']['provider']}/{llm_nodes[0]['data']['model']['name']}" if llm_nodes else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
