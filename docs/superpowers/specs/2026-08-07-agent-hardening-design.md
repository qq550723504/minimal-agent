# Agent Hardening and Workflow Design

## Goal

把当前可运行的 Agent 原型提升到“可安全演示、行为可预测、部署可复现”的状态，同时保持现有 FastAPI、Python 标准库队列和适配器架构，不引入 Redis、Celery 或数据库。

## Scope

本次改造包含五个相互关联的边界：

1. 将异步执行从“每个步骤一个独立任务”改为“一个请求一个 workflow 任务”，保证步骤顺序并提供整体结果。
2. 增加基于环境变量的 API Key 鉴权，并用 API Key 映射出的用户 ID 做任务和记忆隔离。
3. 为 HTTP 工具增加默认拒绝、域名白名单、私网地址拦截、重定向限制和响应大小限制。
4. 修复向量记忆的用户过滤、持久化原子性和损坏数据处理。
5. 修复 CI 和 Docker Compose 的可重复运行问题，并为上述行为补充回归测试。

不包含真实身份系统、数据库队列、管理后台、真实 OpenAI 调用或生产级分布式部署。

## Architecture

### Authentication and ownership

新增认证模块解析 `AGENT_API_KEYS`，格式为 `user_id:key`，多个条目用逗号分隔。除健康检查外的 API 使用 `X-API-Key` 认证；认证成功后得到不可由请求体覆盖的 `user_id`。

当 `AGENT_API_KEYS` 未配置时，开发环境仍允许 API 调用并使用 `default` 用户，以保持 mock 模式的本地易用性。生产部署文档和 Compose 示例配置鉴权变量；设置 `AGENT_AUTH_REQUIRED=true` 后，未配置或错误 Key 一律返回 401。

队列记录保存 `owner_id`。查询单个任务和任务列表只返回当前用户拥有的记录；未知任务和他人任务统一返回 404，避免泄露任务存在性。

### Workflow execution

`enqueue_task_execution` 将完整步骤列表封装为一个队列任务。worker 在同一任务中按列表顺序调用 `execute_step`，返回 `List[str]`；客户端只接收一个 `task_id`。任务失败时记录失败步骤和错误，只有 workflow 级别抛出的异常才触发重试。

现有同步 `execute_tasks` 保持返回结果列表的 API 兼容性。工具异常统一转换成可判断的执行失败，避免异步任务把错误文本误报为成功。

### HTTP tool safety

HTTP 工具在发起请求前解析 URL，仅允许 `http`/`https`，默认要求目标主机命中 `AGENT_HTTP_ALLOWED_HOSTS`。解析后的 IP 地址以及 DNS 解析出的地址不得是 loopback、私有、链接本地、保留或未指定地址；除非显式开启开发开关，不允许访问这些地址。

请求使用固定连接和读取超时、禁止自动跟随重定向，并限制响应体读取大小。策略拒绝使用明确的 `ValueError`，不会向网络发起请求。

### Memory isolation and persistence

向量查询增加 `user_id` 参数，在排序前过滤 metadata 中的 `user_id`。旧数据没有用户字段时视为 `default`，保证迁移可控。记忆文件保存到同目录临时文件后使用替换操作，加载时校验文档、元数据和向量长度，不合法文件抛出清晰错误而不是静默产生错配。

### Deployment and verification

CI 安装依赖失败必须终止 job；服务测试所需依赖必须来自 `requirements.txt`。仓库增加 Prometheus 配置样例，Compose 使用可创建的持久化目录或文件路径，并在 README 中说明 API Key 和 HTTP 白名单配置。

## Error handling

- 输入校验错误由 API 转换为 400，而不是未处理的 500。
- 认证失败返回 401。
- 不属于当前用户的任务按 404 处理。
- SSRF 或 URL 白名单拒绝返回可读错误，且不执行网络请求。
- workflow 内部失败记录 `failed`、失败步骤索引和错误；重试后仍失败才结束任务。
- 向量记忆文件损坏时启动失败并说明路径，避免使用不可信的部分数据。

## Testing strategy

新增或调整以下测试：

- workflow 队列只生成一个任务 ID，并验证多步骤严格按顺序执行。
- API Key 成功认证、缺失/错误 Key 拒绝、任务跨用户不可见。
- 记忆查询只返回当前用户数据，并覆盖旧数据的 `default` 迁移行为。
- HTTP 工具拒绝未白名单域名、私网 IP、重定向和超大响应；允许白名单请求。
- 输入错误返回 400；现有服务、Planner、Executor、Memory 和工具测试继续通过。
- CI 配置不再忽略依赖安装错误，Compose 引用的配置文件存在。

## Acceptance criteria

1. 完整 `python -m pytest -q` 测试套件通过。
2. 多步骤队列任务在多个 worker 配置下仍保持计划顺序。
3. 开启 `AGENT_AUTH_REQUIRED=true` 时，除健康检查外的 API 没有有效 API Key 不可访问。
4. 用户只能读取自己的任务和向量记忆。
5. 默认 HTTP 工具不会访问未授权或内网目标。
6. 新 checkout 能按 README 和 Compose 配置启动服务与 Prometheus。
