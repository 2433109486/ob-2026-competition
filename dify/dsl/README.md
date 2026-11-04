# DSL 说明

## 文件

| 文件 | 用途 | 导入顺序 |
| --- | --- | --- |
| `absurd-court.chatflow.yml` | 主应用（Chatflow，11 节点） | 唯一文件，直接导入 |

本应用不依赖知识库、不依赖自定义插件、不依赖 Dify 内置工具、**也不依赖 Dify 的模型供应商插件**，
因此只需要导入这一个 DSL。法典数据由后端写入 seekdb，模型调用由后端 `/api/v1/llm/chat` 代理。

## 导入步骤

1. Dify 控制台 → 创建应用 → **导入 DSL 文件** → 选择 `absurd-court.chatflow.yml`；
2. 确认三个 HTTP 节点地址：
   - `① 立案检索` → `http://host.docker.internal:8088/api/v1/court/intake`
   - `④ 法官包大仁` → `http://host.docker.internal:8088/api/v1/llm/chat`
   - `⑤ 落库与量刑` → `http://host.docker.internal:8088/api/v1/court/commit`
3. 保存 → 发布 → 打开聊天。

Dify 1.17.1 实测导入结果为 `completed-with-warnings`（0.1.5 → 0.7.0 自动迁移），11 个节点全部保留并成功运行。

## 节点地图

```text
start ─▶ ① code_intake_payload ─▶ http_intake ─▶ code_intake
                                                   │
                                                   ▼
        answer ◀─ code_render ◀─ http_commit ◀─ code_commit_payload
              ▲                        ▲
              │                        │
        code_verdict ◀─ llm_judge ◀─ code_prompt
```

| 节点 | 类型 | 说明 |
| --- | --- | --- |
| start | start | 可选输入 `player_id`；留空用 `sys.user_id` |
| code_intake_payload | code | 构造立案请求 JSON（raw-text） |
| http_intake | http | 调后端 `/api/v1/court/intake` |
| code_intake | code | 解析检索结果，拼提示词区块 |
| code_prompt | code | 组装 system/user 消息（与 `backend/app/prompt.py` 一致） |
| llm_judge | http | 调后端 `/api/v1/llm/chat`，由后端代理模型 |
| code_verdict | code | 解析法官 JSON，失败降级 |
| code_commit_payload | code | 构造结案请求 JSON（raw-text） |
| http_commit | http | 调后端 `/api/v1/court/commit` |
| code_render | code | 渲染判决书 |
| answer | answer | 输出 |

## 换模型

不需要改 DSL。改后端环境变量：

```bash
LLM_BASE_URL=https://api.deepseek.com/v1/chat/completions
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-REPLACE_ME
```

然后重启后端即可。Dify 工作流保持原样。

## 换后端地址

在 Dify 的节点面板里改三个 HTTP 节点的 URL，保存并**重新发布**。
如果 Dify 在 Linux Docker 里，可以给 `api`/`worker` 加：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

## 调试建议

- 单节点测试：先测 `http_intake` 是否 200；
- 看后端：`docker compose -f deploy/docker-compose.yml logs -f court-api`；
- 看 Dify：`docker compose logs -f api`；
- 看数据：`mysql -h 127.0.0.1 -P 2881 -u root -D absurd_court -e "SELECT ..."`。
