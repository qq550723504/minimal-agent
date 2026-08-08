# Minimal Agent 示例

[![CI](https://github.com/qq550723504/minimal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/qq550723504/minimal-agent/actions/workflows/ci.yml)
[![Release](https://github.com/qq550723504/minimal-agent/actions/workflows/release.yml/badge.svg)](https://github.com/qq550723504/minimal-agent/actions/workflows/release.yml)

运行示例：

1. 本地运行：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python src/agent/main.py
```

2. Docker 运行：

```bash
docker build -t minimal-agent .
docker run -it --rm -p 8000:8000 minimal-agent
```

3. Docker Compose 运行：

```bash
docker compose up --build
```

服务运行后：

```bash
curl http://localhost:8000/
```

4. 环境变量说明：

- `AGENT_LLM_BACKEND`: 选择后端，默认 `mock`，可设置为 `openai` 或 `gemini`。
- `OPENAI_MODEL`: OpenAI 模型名称，默认 `gpt-3.5-turbo`。
- `OPENAI_API_KEY`: OpenAI API key（仅当 `AGENT_LLM_BACKEND=openai` 或 `AGENT_EMBEDDING_BACKEND=openai` 时需要）。
- `GEMINI_MODEL`: Gemini 模型名称，默认 `gemini-2.5-flash`。
- `GEMINI_API_KEY`: Gemini API key（仅当 `AGENT_LLM_BACKEND=gemini` 或 `AGENT_EMBEDDING_BACKEND=gemini` 时需要）。
- `AGENT_ENABLE_MEMORY`: 是否启用向量记忆，默认 `true`。
- `AGENT_EMBEDDING_BACKEND`: 嵌入后端，默认 `mock`，可设置为 `openai` 或 `gemini`。
- `OPENAI_EMBEDDING_MODEL`: OpenAI Embedding 模型名称，默认 `text-embedding-3-small`。
- `GEMINI_EMBEDDING_MODEL`: Gemini Embeddings 模型名称，默认 `gemini-embedding-2`。
- `VECTOR_MEMORY_PATH`: 向量记忆持久化文件路径，Docker 默认 `/app/data/vector_memory.json`。
- `QUEUE_WORKER_COUNT`: 后台任务队列工作线程数，默认 `2`。
- `WORKFLOW_STORE_PATH`: SQLite 工作流状态数据库路径，默认 `data/workflows.sqlite3`；Docker 默认 `/app/data/workflows.sqlite3`。
- `AGENT_AUTH_REQUIRED`: 是否强制 API Key 鉴权，默认 `false`；生产环境建议设置为 `true`。
- `AGENT_API_KEYS`: 用户和 API Key 映射，格式为 `user_id:key,user_id2:key2`。
- `AGENT_METRICS_API_KEY`: Prometheus 访问 `/metrics` 的独立 Bearer token。
- `AGENT_HTTP_ALLOWED_HOSTS`: HTTP 工具允许访问的域名，逗号分隔；为空时默认拒绝所有 HTTP 工具请求。
- `AGENT_HTTP_TIMEOUT_SECONDS`: HTTP 工具连接和读取超时，默认 `5` 秒。
- `AGENT_HTTP_MAX_RESPONSE_BYTES`: HTTP 工具最大响应体大小，默认 `1048576` 字节。
- `AGENT_MAX_TOOL_RESULT_BYTES`: 所有能力结果的全局最大 JSON 大小，默认 `1048576` 字节；必须为正数。
- `AGENT_CAPABILITY_RUNTIME_ENABLED`: 是否加载管理员安装的插件与 Skill 目录，默认 `false`。
- `AGENT_PLUGIN_DIR`: 插件根目录，默认 `plugins`；Compose 将项目的 `./plugins` 以只读方式挂载到 `/app/plugins`。
- `AGENT_MCP_ALLOWED_HOSTS`: 生产环境 Streamable HTTP MCP Server 的精确主机名 allowlist，逗号分隔；为空时不允许远程 MCP 连接。
- `AGENT_MCP_STDIO_ALLOWED_COMMANDS`: 允许启动的 MCP stdio 可执行文件路径 allowlist，逗号分隔；必须填写解析后的实际可执行文件，shell 包装器始终拒绝。
- `AGENT_MCP_STARTUP_TIMEOUT_SECONDS`: MCP 配置解析和连接握手各阶段的超时上限，默认每阶段 `30` 秒；必须是有限正数。
- `AGENT_MCP_DISCOVERY_TIMEOUT_SECONDS`: MCP 全部分页工具发现的总超时，默认 `30` 秒；必须是有限正数。
- `AGENT_MCP_SHUTDOWN_TIMEOUT_SECONDS`: 每个 MCP 客户端关闭清理的超时，默认 `10` 秒；必须是有限正数。
- `AGENT_MAX_ACTIVE_SKILLS`: 单次请求最多激活的 Skill 数，默认 `3`。
- `AGENT_MAX_SKILL_REFERENCE_BYTES`: 单个 Skill 参考文件的最大读取字节数，默认 `262144`。

插件、Skill 与 MCP 运行时：

- 默认关闭。设置 `AGENT_CAPABILITY_RUNTIME_ENABLED=true` 后，服务从 `AGENT_PLUGIN_DIR`（默认 `plugins`）下的每个 `<installation>/plugin.yaml` 加载插件。
- 插件目录建议使用只读挂载。每个 Skill 的 `path` 必须指向插件目录内的 UTF-8 `SKILL.md`；参考资料只能通过内置的 `internal.skill_read_reference` 工具读取，且受 `AGENT_MAX_SKILL_REFERENCE_BYTES` 限制。
- MCP stdio 连接必须同时满足 `AGENT_MCP_STDIO_ALLOWED_COMMANDS` 精确可执行文件 allowlist、插件目录内 cwd 和安全环境变量规则；shell 包装器（包括 `.cmd`/`.bat`）始终拒绝。
- MCP Streamable HTTP 连接必须使用 HTTPS、精确主机 allowlist（`AGENT_MCP_ALLOWED_HOSTS`）和安全 DNS 地址；不会跟随重定向或使用代理环境变量。
- `enabled: false` 的插件会记录为 disabled；`required: true` 的插件启动失败会阻止服务启动，普通插件失败只会被禁用。`/api/plugins`、`/api/skills` 和 `/api/tools` 需要鉴权，并且不会返回密钥、命令参数、Skill 正文或参考文件内容。

最小插件示例：

```text
plugins/
└── weather/
    ├── plugin.yaml
    └── skills/
        └── forecast/SKILL.md
```

```yaml
api_version: minimal-agent/v1
id: weather
version: 1.0.0
enabled: true
required: false
skills:
  - id: forecast
    path: skills/forecast/SKILL.md
    triggers: [天气预报]
mcp_servers: []
```

5. API 调用示例：

```bash
curl -X POST http://localhost:8000/api/handle -H "Content-Type: application/json" -d '{"prompt":"hello world"}'

curl -X POST http://localhost:8000/api/handle/queue -H "Content-Type: application/json" -d '{"prompt":"hello world"}'

curl http://localhost:8000/api/tasks
curl http://localhost:8000/api/tools
curl http://localhost:8000/api/plugins
curl http://localhost:8000/api/skills
```

启用 `AGENT_AUTH_REQUIRED=true` 时，API 请求使用 `X-API-Key`；`/docs`、`/redoc` 和 `/openapi.json` 也受同一鉴权保护。任务查询按 API Key 对应的用户隔离。

更多文档：请参见 `docs/AGENT_GUIDE.md`，其中包含架构设计、部署建议、安全与维护策略。

编排与监控：
- `docker-compose.yml` 包含 `agent` 和 `prometheus` 服务。
- `AGENT_ENABLE_MEMORY=true` 和 `VECTOR_MEMORY_PATH=/app/data/vector_memory.json` 已在 Docker 环境中启用。
- 升级旧版 Compose 部署时，请在首次启动新配置前迁移旧版向量记忆：如果项目根目录存在 `vector_memory.json` 且 `data/vector_memory.json` 不存在，PowerShell 执行 `New-Item -ItemType Directory -Force .\data; Copy-Item .\vector_memory.json .\data\vector_memory.json`。
- 生产部署至少应配置 `AGENT_AUTH_REQUIRED=true`、`AGENT_API_KEYS` 和 `AGENT_HTTP_ALLOWED_HOSTS`。
- 切换 `AGENT_EMBEDDING_BACKEND` 或 Embeddings 模型后，向量空间可能不兼容；应删除并重建 `VECTOR_MEMORY_PATH` 中的旧向量数据。
- Prometheus 使用 `./data/metrics-token` 作为 Bearer token；生产环境必须把它替换为与 `AGENT_METRICS_API_KEY` 相同的随机值。
- Compose 会把 `./data` 挂载到容器的 `/app/data`，用于持久化向量记忆、审计日志和 SQLite 工作流状态。
- 插件运行时默认关闭。启用 `AGENT_CAPABILITY_RUNTIME_ENABLED=true` 后，服务仅在启动时从只读插件目录构建目录；`/api/plugins` 和 `/api/skills` 仅返回声明的标识、版本、状态、错误码、触发词和能力名，不返回命令、环境变量、Skill 正文或参考文件内容。
- 队列工作流会在每个步骤完成后保存状态；服务重启后会从第一个未完成步骤恢复。恢复语义是至少一次执行，服务在步骤执行中退出时该步骤可能再次执行。
- 只有通过工作流入口创建的任务支持重启恢复；直接提交任意 Python callable 的内部队列任务不支持跨进程恢复。
- 访问 `http://localhost:9090` 可查看 Prometheus UI。

版本与变更记录：请参见 `CHANGELOG.md`。
```
