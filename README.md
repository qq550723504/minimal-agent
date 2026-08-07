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

- `AGENT_LLM_BACKEND`: 选择后端，默认 `mock`，可设置为 `openai`。
- `OPENAI_MODEL`: OpenAI 模型名称，默认 `gpt-3.5-turbo`。
- `OPENAI_API_KEY`: OpenAI API key（仅当 `AGENT_LLM_BACKEND=openai` 或 `AGENT_EMBEDDING_BACKEND=openai` 时需要）。
- `AGENT_ENABLE_MEMORY`: 是否启用向量记忆，默认 `true`。
- `AGENT_EMBEDDING_BACKEND`: 嵌入后端，默认 `mock`，可设置为 `openai`。
- `OPENAI_EMBEDDING_MODEL`: OpenAI Embedding 模型名称，默认 `text-embedding-3-small`。
- `VECTOR_MEMORY_PATH`: 向量记忆持久化文件路径，Docker 默认 `/app/vector_memory.json`。
- `QUEUE_WORKER_COUNT`: 后台任务队列工作线程数，默认 `2`。
- `AGENT_AUTH_REQUIRED`: 是否强制 API Key 鉴权，默认 `false`；生产环境建议设置为 `true`。
- `AGENT_API_KEYS`: 用户和 API Key 映射，格式为 `user_id:key,user_id2:key2`。
- `AGENT_METRICS_API_KEY`: Prometheus 访问 `/metrics` 的独立 Bearer token。
- `AGENT_HTTP_ALLOWED_HOSTS`: HTTP 工具允许访问的域名，逗号分隔；为空时默认拒绝所有 HTTP 工具请求。
- `AGENT_HTTP_TIMEOUT_SECONDS`: HTTP 工具连接和读取超时，默认 `5` 秒。
- `AGENT_HTTP_MAX_RESPONSE_BYTES`: HTTP 工具最大响应体大小，默认 `1048576` 字节。

5. API 调用示例：

```bash
curl -X POST http://localhost:8000/api/handle -H "Content-Type: application/json" -d '{"prompt":"hello world"}'

curl -X POST http://localhost:8000/api/handle/queue -H "Content-Type: application/json" -d '{"prompt":"hello world"}'

curl http://localhost:8000/api/tasks
curl http://localhost:8000/api/tools
```

更多文档：请参见 `docs/AGENT_GUIDE.md`，其中包含架构设计、部署建议、安全与维护策略。

编排与监控：
- `docker-compose.yml` 包含 `agent` 和 `prometheus` 服务。
- `AGENT_ENABLE_MEMORY=true` 和 `VECTOR_MEMORY_PATH=/app/data/vector_memory.json` 已在 Docker 环境中启用。
- 升级旧版 Compose 部署时，请在首次启动新配置前迁移旧版向量记忆：如果项目根目录存在 `vector_memory.json` 且 `data/vector_memory.json` 不存在，PowerShell 执行 `New-Item -ItemType Directory -Force .\data; Copy-Item .\vector_memory.json .\data\vector_memory.json`。
- 生产部署至少应配置 `AGENT_AUTH_REQUIRED=true`、`AGENT_API_KEYS` 和 `AGENT_HTTP_ALLOWED_HOSTS`。
- Prometheus 使用 `./data/metrics-token` 作为 Bearer token；生产环境必须把它替换为与 `AGENT_METRICS_API_KEY` 相同的随机值。
- Compose 会把 `./data` 挂载到容器的 `/app/data`，用于持久化向量记忆和审计日志。
- 访问 `http://localhost:9090` 可查看 Prometheus UI。

版本与变更记录：请参见 `CHANGELOG.md`。
```
