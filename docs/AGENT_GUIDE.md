# Agent 构建指南

本文档提供从设计、实现到部署的端到端 Agent 构建指南，并附带最小可运行示例与模板。适用于希望尽快得到可验证原型，并在此基础上迭代的工程团队或个人。

## 一、目标与范围
- 目标：构建一个可配置、可观测、可扩展的多步骤 Agent 原型。
- 成功标准：支持输入→规划→执行三步流水线，能调用至少一个外部工具/接口；包含测试、容器化与CI示例。

## 二、架构概览
- 模块：感知(Perception)、记忆(Memory)、规划(Planner)、执行(Executor)、工具适配(Tools)、安全(Safety)、监控(Observability)。
- 接口：统一的请求/响应契约（JSON）、请求ID、超时与重试策略。

## 三、开发与依赖
- 推荐语言：Python 3.11+（示例基于 Python）。
- 依赖管理：运行时使用 `requirements.txt`，测试和 CI 使用 `requirements-dev.txt`；如需构建可发布包，再引入 `pyproject.toml`。

示例：
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 四、最小可行 Agent (MVP)
- 功能：接收文本输入，生成简单计划，执行计划（调用本地函数或HTTP API），返回结果。
- 支持异步队列执行：将任务加入后台队列，并通过任务状态查询接口查看执行结果。
- 支持记忆持久化：将向量记忆保存到磁盘，并在下次运行时加载历史记忆。
- 设计点：模块化（便于替换模型与工具）、日志与 trace、错误补偿策略。

### 4.1 队列与任务状态
项目提供 `/api/handle`、`/api/handle/queue`、`/api/tasks`、`/api/tools`、`/api/plugins` 和 `/api/skills` 接口：
- `/api/handle`：同步执行一次规划与工具调用。
- `/api/handle/queue`：接收请求并将执行任务加入后台队列。
- `/api/tasks`：查询任务状态、重试次数和执行结果。
- `/api/tools`：列出当前可用工具及其描述。
- `/api/plugins`：列出管理员安装插件的安装名、标识、版本、启用状态、稳定错误码及声明能力名。
- `/api/skills`：列出已加载 Skill 的全局标识、所属插件和触发词。

插件与 Skill 运行时默认由 `AGENT_CAPABILITY_RUNTIME_ENABLED=false` 关闭；关闭时服务不会访问 `AGENT_PLUGIN_DIR`，两个目录接口返回空列表。启用后，服务启动时读取已验证的插件清单、建立 Skill 目录并注册内部参考读取工具；必需插件的加载错误会阻止启动。生产 Compose 将 `./plugins` 以只读方式挂载到 `/app/plugins`。目录接口不会泄露插件命令、环境变量值、Skill 指令或参考文件内容。

插件清单位于 `<AGENT_PLUGIN_DIR>/<installation>/plugin.yaml`，使用 `minimal-agent/v1` 契约。清单字段包括插件版本、启用/必需标志、Skill 声明和 MCP Server 声明；未知字段、重复 ID/触发词、非严格布尔值和非有限 timeout 都会被拒绝。Skill ID 会按插件 ID 做全局命名空间编码，MCP Server 与工具名同样避免点号分段碰撞。

MCP Server 支持两种传输：
- `stdio`：命令必须命中精确 allowlist，cwd 必须位于插件目录内，环境变量只允许从显式映射注入；shell 包装器和 Windows 批处理包装器拒绝。
- `streamable_http`：生产环境要求 HTTPS 和精确主机 allowlist；DNS 返回地址会在连接前校验并固定，禁止重定向和代理环境变量。MCP 生命周期、工具发现、工具执行和结果大小均有独立边界。

建议至少配置：`AGENT_MCP_ALLOWED_HOSTS`、`AGENT_MCP_STDIO_ALLOWED_COMMANDS`、`AGENT_MAX_TOOL_RESULT_BYTES`、`AGENT_MAX_ACTIVE_SKILLS` 和三个 `AGENT_MCP_*_TIMEOUT_SECONDS` 变量。所有 MCP allowlist 默认拒绝，超时必须是有限正数。

队列工作流使用 `WORKFLOW_STORE_PATH` 指定的 SQLite 数据库保存工作流定义、步骤结果、重试状态和生命周期事件。每个步骤完成后立即提交状态；服务重启时会把中断中的工作流恢复为待执行，并从第一个未完成步骤继续。该机制提供至少一次执行语义，步骤执行期间进程退出可能导致该步骤再次执行。任意 Python callable 直接提交到内部队列仍仅支持进程内执行，不支持跨进程恢复。

当前队列由单个进程内工作线程和 SQLite 文件组成，生产部署应保持单实例；多副本部署前应采用成熟的外部队列和共享数据库，并重新验证任务领取、幂等性和恢复语义。

### 4.2 向量记忆持久化
`src/agent/vector_memory.py` 提供 `save(path)` 和 `load(path)` 方法，适合用于简单的磁盘持久化或作为构建持久化记忆层的基础。

### 4.3 RAG 提示构建
Planner 会从向量记忆中检索与当前请求最相关的历史记忆，并将最近的对话历史一起注入到最终发送给 LLM 的提示中。

检索增强生成（RAG）策略包括三个明确部分：
- `System`: 系统指令，定义代理角色和行为。
- `Conversation history`: 最近的用户交互历史，用于保持上下文连续性。
- `Relevant memory`: 基于当前请求检索出的相关向量记忆。
- `Task`: 当前需要完成的具体目标。
- `Response format`: 规定输出结构，便于下游解析。

当前示例使用 JSON 数组作为规划输出格式，利于后续执行引擎直接解析每一步。

执行器当前支持以下工具调用示例：
```text
http_get: {"url": "https://api.example.com/data", "params": {"q": "test"}}
http_post: {"url": "https://api.example.com/items", "json": {"name": "agent"}}
```

这种组合策略可增强：
- 对长期记忆事实的访问能力
- 对当前任务的上下文理解
- 连贯的多轮交互体验

如果没有检索到相关记忆或历史记录，Planner 会直接使用用户原始请求。

## 五、测试策略
- 单元测试：模块内部逻辑。
- 集成测试：模拟工具/API（stub/mocks），覆盖插件加载、Skill 参考读取、MCP stdio/Streamable HTTP 生命周期和安全边界。
- 回归测试：验证 allowlist、SSRF/DNS 固定、跨平台路径、命名空间碰撞、unknown outcome、结果大小和非有限 timeout。
- 场景回放：保存对话与事件用于回放验证。

## 六、部署与运维
- 容器化：提供 `Dockerfile`，镜像中包含运行时与入口。
- 编排：建议 Kubernetes 或 Serverless；先灰度再放量。
- 监控：Prometheus/Grafana 指标、ELK/EFK 日志聚合。
- 本地开发使用 `docker compose up --build`。生产环境使用 `docker compose -f docker-compose.yml -f docker-compose.production.yml up --build`，并提供 `AGENT_API_KEYS`、`AGENT_METRICS_API_KEY` 和 `AGENT_HTTP_ALLOWED_HOSTS`；生产模式会在启动时拒绝不安全配置。

## 七、安全与合规
- 最小权限、输入校验、审计日志、PII 识别与删除策略。

## 八、示例模板说明
工作区包含 `src/agent` 的最小示例：
- `src/agent/main.py`: 最小主循环与核心方法 `handle_input()` 和 `enqueue_input()`。
- `src/agent/task_queue.py`: 本地任务队列实现示例。
- `tests/test_agent.py`: 简单断言。
- `tests/test_task_queue.py`: 验证任务队列功能。
- `Dockerfile`: 构建镜像示例。
- `.github/workflows/ci.yml`: CI 验证示例（运行测试）。

## 九、发布前检查清单
- 核心用例通过回放测试。
- 敏感数据流经审计并采取保护。
- 监控与告警就绪。

## 十、维护与迭代建议
- 版本管理：采用语义化版本号（MAJOR.MINOR.PATCH）；重大变更编写发布说明。
- 分支策略：使用 `main`/`develop`、feature 分支、PR 审查，保证主分支始终可部署。
- 回归测试：在 CI 中加入单元、集成与关键路径回归测试；每次依赖升级都执行测试套件。
- 依赖更新：定期检查 `requirements.txt`，使用 `pip list --outdated` 或 Dependabot 自动升级。
- 文档同步：把接口说明、运行步骤、部署方式和监控指南都写入 `docs/`；每次代码变更同步更新文档。
- 监控阈值：定义关键指标（请求成功率、延迟、错误率、CPU/内存）和告警策略；定期审查报警有效性。
- 可用性与回滚：生产环境部署应支持灰度/金丝雀发布；失败时快速回滚并恢复前一稳定版本。
- 维护计划：建立定期迭代周期，包含性能回归检查、安全审计、模型与数据依赖评审。
- 日志与审计：持续检查审计日志与异常日志，确保安全事件可追溯。

---
如需我把这些模板或示例拓展为更复杂的能力（向量记忆、外部LLM集成、任务队列、多线程执行等），告诉我你优先的方向。
