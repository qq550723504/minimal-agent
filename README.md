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

4. API 调用示例：

```bash
curl -X POST http://localhost:8000/api/handle -H "Content-Type: application/json" -d '{"prompt":"hello world"}'

curl -X POST http://localhost:8000/api/handle/queue -H "Content-Type: application/json" -d '{"prompt":"hello world"}'

curl http://localhost:8000/api/tasks
```

更多文档：请参见 `docs/AGENT_GUIDE.md`，其中包含架构设计、部署建议、安全与维护策略。

编排与监控：
- `docker-compose.yml` 包含 `agent` 和 `prometheus` 服务。
- `AGENT_ENABLE_MEMORY=true` 和 `VECTOR_MEMORY_PATH=/app/vector_memory.json` 已在 Docker 环境中启用。
- 访问 `http://localhost:9090` 可查看 Prometheus UI。

版本与变更记录：请参见 `CHANGELOG.md`。
```