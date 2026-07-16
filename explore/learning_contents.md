# nanobot 学习路径规划

> 基于 nanobot 项目实际结构制定（核心 `loop.py` 2017 行 / `runner.py` 1390 行）。
> 总体策略：**由外向内 → 主干 → 扩展面**，分 6 个阶段，每阶段配一个"过关标志"，能答出就算过关。

---

## 阶段 0：跑起来（1 天）

**目标**：让肌肉记忆先于抽象理解。

- 跟 `README.md` 装 deps，`pip install -e ".[dev]"`
- 启动 gateway：`nanobot gateway`
- 启动 WebUI：`cd webui && bun run dev`
- 用 WebUI 跑一轮对话，观察后台日志里 InboundMessage → LLM → Tool → OutboundMessage 的轨迹
- 看 `~/.nanobot/config.json` 的结构（对应 `nanobot/config/schema.py`）

**过关标志**：能说清楚一次对话从用户输入到回复输出，经过了哪些进程/协程。

---

## 阶段 1：消息总线 + 数据流骨架（2 天）

这是整个系统的"血管"，先打通它，后面所有模块都是挂在血管上的器官。

按顺序读：

1. `nanobot/bus/queue.py`（44 行，最小）—— `MessageBus`、`InboundMessage`、`OutboundMessage`
2. `nanobot/channels/base.py`（276 行）—— 通道抽象，看消息怎么 publish 进 bus
3. `nanobot/nanobot.py` + `nanobot/cli/commands.py` —— 启动装配，理解 bus / channels / agent loop 怎么连起来

**过关标志**：自己画一张时序图，标出 Telegram 一条消息 → bus → AgentLoop → bus → Telegram 的全过程。

---

## 阶段 2：Agent 主干（4–5 天，最核心）

这是项目最重的部分，按"调度者 → 执行者"分层。

### 2a. `nanobot/agent/loop.py`（2017 行）—— 先读前 300 行 + 类的方法清单

- `AgentLoop` 是**协调者**：session 路由、hook 调度、context 构建
- 重点找：`handle_inbound` / `dispatch` / session key 构造 / hook 装配点

### 2b. `nanobot/agent/runner.py`（1390 行）

- `AgentRunner` 是**真正的对话循环**：发消息给 provider → 解析 tool_calls → 执行 tool → 回灌 → 再调 provider
- 这一段是 agent 框架的"心脏"，建议**边读边打断点跑一次**，对照日志看每一步

### 2c. 配套子系统（挑着读）

- `nanobot/agent/memory.py` —— 注意 **atomic write** 那段（temp+fsync+rename+dirfsync），作者特意强调过不要改成普通 `open("w")`
- `nanobot/session/manager.py` + `goal_state.py` —— TTL 压缩 + sustained goal
- `nanobot/agent/hooks/` —— hook 机制

**过关标志**：能解释清楚 "tool_call 链是怎么收尾的"——也就是 LLM 不再发 tool_call 时 runner 怎么决定退出循环。

---

## 阶段 3：Provider 抽象（2 天）

- `nanobot/providers/base.py`（979 行）—— 所有 LLM 提供商的父类，定义了 `_call()` 契约、流式接口、tool_call 格式归一化
- 挑**一个**具体实现精读（推荐 `providers/openai.py` 或 `providers/anthropic.py`）
- `factory.py` + `registry.py` —— 模型发现和实例化
- 跳过：Azure / Bedrock / Copilot / Codex 这些差异型 provider，等要扩展再看

**过关标志**：能写一个最小化的 echo provider（mock 一个 `_call`）并跑通一次对话。

---

## 阶段 4：工具系统 + 安全边界（3 天）

这是 agent "能动手"的关键，也是后面要做扩展最容易踩坑的地方。

- `nanobot/agent/tools/registry.py`（211 行）—— ToolRegistry，先理解注册 + 发现机制
- `nanobot/agent/tools/filesystem.py` —— **重点看 `_resolve_path`**，这是 workspace 沙箱的核心
- `nanobot/agent/tools/shell.py` + `nanobot/agent/tools/sandbox.py` —— bwrap 后端
- `nanobot/security/network.py` —— `validate_url_target`，所有 outbound HTTP 必经之地
- 跳着扫：`web_search.py` / `mcp.py` / `cron.py` / `long_task.py` / `subagent.py`

**过关标志**：能解释"为什么不能在工具里直接用 `open(path)` 或 `httpx.get(url)`"，以及绕过 `_resolve_path` / `validate_url_target` 会带来什么后果。

---

## 阶段 5：扩展面（按需，各 1 天）

到这里主干已经通，剩下的是"挂载点"，挑感兴趣的学：

| 方向 | 入口文件 |
|---|---|
| 新增 Channel | `channels/base.py` + 一个最简单的 channel（如 `websocket.py`）|
| WebUI / Gateway | `webui/` + `nanobot/gateway/` + `nanobot/api/server.py`（OpenAI 兼容 API）|
| Skills 机制 | `nanobot/skills/` 几个 markdown + `skill-creator` |
| 心跳 / 长任务 | `nanobot/heartbeat/` + `agent/tools/long_task.py` |
| 模板系统 | `nanobot/templates/`（改 prompt = 改 agent 行为）|
| 配对 / 权限 | `nanobot/pairing/` |

---

## 学习方法建议

1. **每个模块读完都跑一次**——这个项目的好处是有真实可跑的 WebUI，看代码 + 看日志效果最好
2. **善用 `tests/`**——`tests/agent/conftest.py` 里的 `make_provider()` 和 `make_loop()` 是非常宝贵的"最小可运行样例"，比读源码更快理解装配关系
3. **先读 `AGENTS.md` + `.agent/design.md` + `.agent/security.md`**——这是作者写的设计约束，比代码更能告诉你"为什么这么写"
4. **不要试图一次性啃完 `loop.py`（2017 行）**——先扫方法清单，再按一次真实对话的调用栈定位到具体方法精读

---

## 核心文件清单（速查）

| 文件 | 行数 | 作用 |
|---|---|---|
| `nanobot/bus/queue.py` | 44 | 消息总线，解耦 channels 和 agent |
| `nanobot/channels/base.py` | 276 | 所有 channel 的父类 |
| `nanobot/agent/loop.py` | 2017 | AgentLoop：协调者 |
| `nanobot/agent/runner.py` | 1390 | AgentRunner：真正的 LLM 对话循环 |
| `nanobot/agent/memory.py` | — | 会话持久化 + Dream 两阶段记忆 |
| `nanobot/providers/base.py` | 979 | LLM provider 父类 |
| `nanobot/agent/tools/registry.py` | 211 | 工具注册中心 |
| `nanobot/config/schema.py` | — | Pydantic 配置 schema |

---

## 时间预算总览

| 阶段 | 时长 | 性质 |
|---|---|---|
| 0. 跑起来 | 1 天 | 必做 |
| 1. 总线 + 数据流 | 2 天 | 必做 |
| 2. Agent 主干 | 4–5 天 | 必做（最核心）|
| 3. Provider 抽象 | 2 天 | 必做 |
| 4. 工具 + 安全 | 3 天 | 必做 |
| 5. 扩展面 | 按需 | 选学 |
| **合计（主干）** | **~12–13 天** | |

