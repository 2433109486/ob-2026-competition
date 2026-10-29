# DSL 说明

## 文件

| 文件 | 用途 | 导入顺序 |
| --- | --- | --- |
| `absurd-court.chatflow.yml` | 主应用（Chatflow，8 节点） | 唯一文件，直接导入 |

本应用不依赖知识库、不依赖自定义插件、不依赖 Dify 内置工具，因此**只需要导入这一个 DSL**。
法典数据由后端在启动时写入 seekdb，不走 Dify 知识库。

## 导入步骤

1. Dify 控制台 → 创建应用 → **导入 DSL 文件** → 选择 `absurd-court.chatflow.yml`；
2. 打开 `③ 法官包大仁`，绑定你工作区可用的对话模型（默认 `minimax / MiniMax-Text-01`）；
3. 确认 `① 立案检索`、`⑤ 落库与量刑` 的 URL 指向庭审后端：
   - Dify 在 Docker 中：`http://host.docker.internal:8088`
   - Dify 与后端同机直跑：`http://127.0.0.1:8088`
4. 保存 → 发布 → 打开聊天。

> DSL 版本为 `0.1.5`。Dify 1.x 导入时可能提示「版本较低，将自动迁移」，确认即可；
> 节点、边、变量引用都会保留。

## 节点地图

```text
start ──▶ ① http_intake ──▶ ② code_intake ──▶ ③ llm_judge
                                                   │
                                                   ▼
        answer ◀── ⑦ code_render ◀── ⑥ http_commit ◀── ④ code_verdict
```

| 节点 | 说明 | 需要改的地方 |
| --- | --- | --- |
| start | 可选输入 `player_id`；留空用 `sys.user_id` | 无 |
| http_intake | 调 `/api/v1/court/intake` | 后端地址 |
| code_intake | 解析检索结果，拼提示词区块 | 一般不用改 |
| llm_judge | 法官人格 + 输出 JSON 约束 | **模型**；可调温度/长度 |
| code_verdict | 提取 JSON，失败降级 | 一般不用改 |
| http_commit | 调 `/api/v1/court/commit` | 后端地址 |
| code_render | 渲染判决书 | 可改文案/表情 |
| answer | 输出 | 无 |

## 换模型

提示词不依赖任何特定模型，只要求：

- 支持中文；
- 能稳定输出 JSON（Claude、GPT、DeepSeek、Qwen、MiniMax 均可）；
- 上下文 ≥ 8k（提示词里含 3 条法条 + 至多 5 条记忆 + 判例，通常 < 3k tokens）。

换模型后建议先跑一轮「立案」，确认 `code_verdict.parse_ok = 1`。如果模型经常不输出 JSON，
可以在 LLM 节点里把温度降到 0.6，或启用 Dify 的「结构化输出」功能（新版支持）。

## 换后端地址

Dify 的 HTTP 节点地址在节点面板里改，改完保存并**重新发布**。
如果 Dify 在 Linux Docker 里，除了改地址，也可以给 `api`/`worker` 加：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

## 调试建议

- 单节点测试：Dify 支持对单个节点「运行」，可先测 `http_intake` 是否返回 200；
- 看变量：在 `code_intake` 节点里临时加 `return {"debug": raw}` 不方便，推荐直接看 Dify 的节点执行详情；
- 看后端：`docker compose -f deploy/docker-compose.yml logs -f court-api`；
- 看数据：`mysql -h 127.0.0.1 -P 2881 -u root -D absurd_court -e "SELECT ..."`。
