# 农业应用（Agri）工具注册与代码流程

## 概览

农业应用工具让 LLM 可以通过 function calling 调用远程农业算法服务，实现栽秧质量检测、秧苗检测、秋草识别等五类农业场景的图像分析。

工具注册的完整链路：

```
配置文件 config.json
  → Config schema 解析
  → ToolLoader 自动发现
  → ToolRegistry 注册
  → AgentRunner 传递给 LLM
  → LLM 返回 tool_call
  → 执行并返回结果
```

---

## 1. 配置层

### 1.1 用户配置 (`~/.nanobot/config.json`)

```json
{
  "tools": {
    "algo": {
      "enabled": true,
      "baseUrl": "http://xxx.xxx.xxx:8000"
    }
  }
}
```

配置项放在 `tools.algo` 下（不是顶层）。

### 1.2 Schema 定义 (`nanobot/config/schema.py`)

```python
# schema.py:246
class AlgoConfig(Base):
    """Agricultural application service configuration."""
    enabled: bool = False
    base_url: str = ""

# schema.py:305 — 嵌入 ToolsConfig
class ToolsConfig(Base):
    ...
    algo: AlgoConfig = Field(default_factory=AlgoConfig)   # ← 关键
    ...
```

**为什么放在 `ToolsConfig` 而不是根 `Config`：**

`ToolLoader` 传给工具的 `ctx` 是 `ToolContext`，其中 `ctx.config` 是 `ToolsConfig` 实例（不是根 `Config`）。如果 `AlgoConfig` 定义在根 `Config` 上，`AgriTool.enabled()` 访问 `ctx.config.algo` 会找不到字段，工具永远不会被注册。

---

## 2. 工具定义层

### 2.1 工具类 (`nanobot/agent/tools/agri.py`)

每个工具必须继承 `Tool` 基类，实现以下关键部分：

```python
@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(..., enum=("list", "list_data", "start", ...)),
        service_name=StringSchema(..., nullable=True),
        ...
        required=["action"],
    )
)
class AgriTool(Tool):
    name = "agri"                    # LLM 看到的函数名
    description = "Manage ..."       # LLM 看到的函数说明
    _scopes = {"core"}               # 工具作用域

    @classmethod
    def enabled(cls, ctx) -> bool:   # 决定是否加载
        return ctx.config.algo.enabled and bool(ctx.config.algo.base_url)

    @classmethod
    def create(cls, ctx) -> Tool:    # 构造实例
        return cls(base_url=ctx.config.algo.base_url)

    async def execute(self, **kwargs) -> str:  # 实际执行逻辑
        ...
```

**三个关键类方法的调用时机：**

| 方法 | 调用者 | 作用 |
|------|--------|------|
| `enabled(ctx)` | `ToolLoader.load()` | 判断是否注册此工具 |
| `create(ctx)` | `ToolLoader.load()` | 创建工具实例 |
| `execute(**kwargs)` | `ToolRegistry.execute()` | LLM 发起 tool_call 时执行 |

### 2.2 Schema 生成

`@tool_parameters` 装饰器将参数定义转换为 JSON Schema，`Tool.to_schema()` 生成 OpenAI function calling 格式：

```python
# base.py:252
def to_schema(self):
    return {
        "type": "function",
        "function": {
            "name": "agri",
            "description": "Manage agricultural application tasks...",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": [...]},
                    "service_name": {"type": ["string", "null"], ...},
                    ...
                },
                "required": ["action"]
            }
        }
    }
```

---

## 3. 自动发现与注册

### 3.1 ToolLoader 发现 (`nanobot/agent/tools/loader.py`)

```
ToolLoader.discover()
  → pkgutil.iter_modules(nanobot/agent/tools/)
  → 遍历每个模块，找到 Tool 子类
  → 过滤：非抽象、非跳过模块、_plugin_discoverable=True
  → 返回 [AgriTool, ExecTool, ReadFileTool, ...]
```

跳过列表（`_SKIP_MODULES`）包括 `base`, `schema`, `registry`, `loader`, `context` 等，只扫描具体工具实现。

### 3.2 注册流程 (`loader.py:86-116`)

```python
def load(self, ctx, registry, scope="core"):
    for tool_cls in self.discover():
        # 1. 检查 scope
        if scope not in tool_cls._scopes:
            continue

        # 2. 检查是否启用
        if not tool_cls.enabled(ctx):
            continue                                   # ← AgriTool.enabled() 在这里被调用

        # 3. 创建实例
        tool = tool_cls.create(ctx)                    # ← AgriTool.create() 在这里被调用

        # 4. 注册到 Registry
        registry.register(tool)
```

### 3.3 启动入口 (`nanobot/agent/loop.py:458-484`)

```python
def _register_default_tools(self):
    ctx = ToolContext(
        config=self.tools_config,    # ← ToolsConfig 实例
        workspace=str(self.workspace),
        ...
    )
    loader = ToolLoader()
    registered = loader.load(ctx, self.tools)   # ← self.tools 是 ToolRegistry
```

---

## 4. LLM 调用链路

### 4.1 传递工具定义给 LLM

```
AgentLoop 处理用户消息
  → AgentRunner.run(spec)
  → spec.tools.get_definitions()          # ToolRegistry 收集所有工具 schema
  → _build_request_kwargs(tools=...)       # runner.py:640
  → provider.chat(tools=[...])             # 传入 API 请求
  → OpenAI API: chat.completions.create(
        model="deepseek-v4",
        messages=[...],
        tools=[                            # ← LLM 在这里看到所有工具
            {"type": "function", "function": {"name": "agri", ...}},
            {"type": "function", "function": {"name": "read_file", ...}},
            ...
        ]
    )
```

对应代码位置：

- `runner.py:643` — `tools=spec.tools.get_definitions()`
- `runner.py:605-607` — `kwargs["tools"] = tools`
- `openai_compat_provider.py:694-696` — `if tools: kwargs["tools"] = tools`

### 4.2 LLM 返回 tool_call → 执行

```
LLM 响应包含 tool_calls:
  {"name": "agri", "arguments": {"action": "list"}}
      ↓
runner._execute_tools()
  → registry.execute("agri", {"action": "list"})
      ↓
AgriTool.execute(action="list")
  → AgriClient.list_services()             # HTTP GET /list_service
  → 返回 JSON 字符串
      ↓
结果追加到 messages，继续 LLM 对话
  → LLM 根据结果生成最终回复
```

### 4.3 系统提示词组装 (`nanobot/agent/context.py:67-108`)

系统提示词不影响工具注册，但影响 LLM 使用工具的效果：

```
1. identity.md    — 运行时信息、工作空间路径
2. AGENTS.md      — 工作空间自定义指令
3. SOUL.md        — Agent 性格
4. USER.md        — 用户偏好
5. tool_contract.md — 通用工具使用规范
6. Memory         — 长期记忆
7. Active Skills  — always=true 的技能（自动注入）
8. Skills Summary — 可用技能列表（按需加载）
9. Recent History — 最近对话历史
```

---

## 5. 前端面板接入

### 5.1 HTTP 路由 (`nanobot/agri/routes.py`)

前端面板通过 HTTP GET 请求 `/api/agri/*` 路径与后端交互：

```
/api/agri/scenarios         → handle_scenarios()       场景列表
/api/agri/services          → handle_services()        服务列表
/api/agri/tasks             → handle_tasks()           任务列表
/api/agri/status/<name>     → handle_service_status()  服务状态
/api/agri/task/<id>         → handle_task_status()     任务状态
/api/agri/start/<name>      → handle_start()           启动任务
/api/agri/stop/<name>       → handle_stop()            停止任务
/api/agri/data              → handle_list_data()       数据文件列表
```

### 5.2 WebSocket Channel 路由分发 (`nanobot/channels/websocket.py`)

Gateway 的 WebSocket channel 同时处理 WS 连接和 HTTP 请求：

```python
# websocket.py:760-764
async def _dispatch_http(self, connection, request):
    ...
    if got.startswith("/api/agri/"):
        from nanobot.agri.routes import dispatch_agri_route
        resp = await dispatch_agri_route(self, got, request)
        if resp is not None:
            return resp
    ...
```

### 5.3 AgriClient 初始化 (`websocket.py:610-626`)

```python
def _init_agri_client(self):
    cfg = load_config()
    agri_cfg = cfg.tools.algo if cfg.tools.algo.enabled else cfg.algo  # 兼容新旧配置位置
    if not agri_cfg.enabled or not agri_cfg.base_url:
        return None
    return AgriClient(agri_cfg.base_url)
```

客户端存储在 `self._agri_client`，供 routes 的 `_get_client()` 读取。

### 5.4 前端组件结构

```
webui/src/
  lib/
    agri-api.ts              — API 客户端，类型定义（ApplicationInfo, Scenario, TaskInfo...）
  components/
    agri/
      AgriPanel.tsx          — 主面板：左侧场景列表 + 右侧详情
      ScenarioCard.tsx       — 场景卡片
      ApplicationRunner.tsx  — 应用选择、文件选择、启动/停止、进度展示
      TaskHistory.tsx        — 任务历史表格
  App.tsx                    — ShellView type "agri"，路由到 AgriPanel
  components/
    Sidebar.tsx              — 侧边栏按钮，触发 onOpenAgri
```

### 5.5 前端 API 调用链路

```
用户点击侧边栏"农业应用"
  → setView("agri")
  → AgriPanel 挂载
  → fetchScenarios(token)    → GET /api/agri/scenarios  → AgriClient.list_services()（远程）
  → fetchTasks(token)        → GET /api/agri/tasks      → AgriClient.tasks()（远程）
  → 用户选择应用
  → fetchDataFiles(token, name) → GET /api/agri/data?agri_name=xxx → AgriClient.list_data()
  → 用户点击"启动应用"
  → startService(token, name, file) → GET /api/agri/start/<name>?filename=xxx → AgriClient.start_service()
  → 轮询进度
  → fetchTaskStatus(token, id) → GET /api/agri/task/<id> → AgriClient.task_status()
```

---

## 6. 远程服务接口

`AgriClient`（`nanobot/agri/client.py`）是与远程农业算法服务通信的 HTTP 客户端，基于 httpx：

| 方法 | HTTP | 远程端点 | 说明 |
|------|------|----------|------|
| `list_services()` | GET | `/list_service` | 列出所有算法服务 |
| `start_service(name, file)` | POST | `/start_service/<name>` | 启动算法任务 |
| `service_status(name)` | GET | `/service_status/<name>` | 查询服务状态 |
| `task_status(task_id)` | GET | `/task_status/<task_id>` | 查询任务状态 |
| `tasks()` | GET | `/tasks` | 列出所有任务 |
| `tasks_by_service(name)` | GET | `/tasks/<name>` | 按服务名过滤任务 |
| `stop_service(name)` | POST | `/stop_service/<name>` | 停止服务 |
| `list_data(name)` | POST | `/list_data` | 列出输入数据文件 |

注意：`list_data` 的请求体是 `{"algo_name": name}`，这里的 `algo_name` 是远程服务的 API 参数名，不随 nanobot 内部命名变化。

---

## 7. 五类农业场景

定义在 `nanobot/agri/scenarios.py`：

| 场景 ID | 名称 | 包含的应用 |
|---------|------|-----------|
| `transplant_quality` | 栽秧质量检测 | `daosui`（稻穗检测）、`yangmiao`（秧苗检测） |
| `lodging` | 倒伏监测 | 无（暂未接入） |
| `growth` | 长势监测 | 无（暂未接入） |
| `weed` | 稻田杂草 | `qiuchao`（秋草识别） |
| `wheat_height` | 小麦株高 | 无（暂未接入） |

每个应用（Application）包含名称、描述和算法步骤（steps）列表。

---

## 8. 添加新工具的 Checklist

以本次 agri 工具为参考，添加新工具需要：

1. **配置**：在 `ToolsConfig` 中添加配置字段（`nanobot/config/schema.py`）
2. **工具类**：在 `nanobot/agent/tools/` 下创建工具文件，实现 `name`、`description`、`enabled()`、`create()`、`execute()`
3. **参数 Schema**：用 `@tool_parameters` + `tool_parameters_schema()` 声明参数
4. **用户配置**：在 `~/.nanobot/config.json` 的 `tools` 下添加对应配置
5. **前端面板**（可选）：创建组件、注册路由、更新 API 客户端
6. **构建前端**：`cd webui && npm run build`（或 `bun run build`）

无需修改 `loader.py`、`registry.py`、`runner.py`——自动发现机制会处理。
