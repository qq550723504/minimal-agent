# park_energy 与 minimal-agent 本地并行运行设计

## 目标

让 `minimal-agent` 与内置的 `park_energy` MCP 服务能够通过同一个 Docker Compose 项目同时启动，并允许 `park_energy` 在没有真实园区能耗 REST API 或凭据时返回可重复的 mock 数据。

本地机器已有其他服务占用 `8000`，因此宿主机端口必须可配置；容器内部仍保持 agent `8000`、park-energy `8100` 的固定端口。

## 方案

新增 `PARK_ENERGY_DATA_MODE` 配置，取值为 `rest` 或 `mock`：

- `rest` 保持当前行为，使用 `EnergyRESTClient` 请求上游 API。
- `mock` 使用独立的 `MockEnergyClient`，为五个 MCP 工具返回稳定、结构化、与请求参数关联的示例结果；不会发起网络请求，也不会读取真实 token。
- 非法模式在配置加载时立即报错，避免误以为已经连接真实数据源。

Compose 增加 `park_energy` 服务，并将其默认配置为 mock 模式。agent 服务保留项目既有的安全默认值：插件运行时、结构化工具调用和 MCP 主机 allowlist 默认关闭/为空；Compose 同时启动两个服务，但本地 HTTP MCP 仅作为直接 MCP 客户端的 mock 端点，agent 接入需要 HTTPS 网关。park-energy 只向宿主机发布 `127.0.0.1:8100`。

agent 的宿主机端口改为 `${AGENT_HOST_PORT:-8000}:8000`，本机验证时设置 `AGENT_HOST_PORT=8001`，不停止现有 `rembg-api`。

## 测试与验收

- 配置测试覆盖默认 `rest`、显式 `mock` 和非法模式。
- mock 客户端测试覆盖五个工具的稳定响应结构，并确认同一查询重复返回相同结果。
- Compose 配置检查确认两个服务、端口、环境变量和健康检查存在且可渲染。
- 启动后验证：`minimal-agent` 根路径返回 200；`park_energy` MCP 握手成功；直接连接 `park_energy` 时发现五个能耗工具。
- 通过直接 MCP 工具调用至少验证一个趋势查询返回 mock 数据；本地 HTTP MCP 不宣称已接入 agent，因为当前 agent 管理器统一要求 HTTP MCP 使用 HTTPS。

## 边界

本次不改变真实 REST API 的路径协议、不增加数据库、不引入随机数据生成器，也不将 mock 模式用于生产 Compose。真实服务仍通过 `PARK_ENERGY_DATA_MODE=rest` 和现有 `ENERGY_*` 配置启用。
