# `nanobot/agent/loop.py` 精读

> 文件行数：~2000 行。本文按"心智模型 → 数据结构 → 装配 → 主循环 → 状态机 → 桥接 → 恢复与持久化 → 并发模型 → 不变量"的顺序逐层展开。
> 阅读时建议对照源码：所有 `file:line` 引用都基于 `nanobot/agent/loop.py`，跨文件会显式注明。

---

## 0. 文件定位：nanobot 的"turn 编排器"

`AgentLoop` 是整个 agent 的核心引擎，但要注意"loop"在这个项目里被重载了，实际上有 **三层嵌套循环**，必须在脑子里分层：

| 层 | 代码位置 | 职责 | 触发节奏 |
|---|---|---|---|
| L1：**进程级主循环** | `AgentLoop.run()` (`loop.py:1018`) | 从 `MessageBus` 消费 `InboundMessage`，决策路由，派发 task | 进程生命周期内常驻 |
| L2：**单 turn 状态机** | `_process_message()` (`loop.py:1311`) 驱动 8 个 `_state_*` handler | 把一条消息变成一次完整响应（恢复 → 压缩 → 命令 → 构建 → 执行 → 落盘 → 响应） | 每条入站消息跑一次 |
| L3：**LLM↔工具迭代循环** | `AgentRunner.run()`（在 `runner.py` 中） | 反复调 LLM、执行工具调用，直到模型不再要工具或撞上限 | L2 的 `_state_run` 内部反复跑 |

`loop.py` 负责 L1 与 L2，**L3 完全委托给 `AgentRunner`**（通过 `_run_agent_loop` 桥接）。这一点是阅读本文的关键：`loop.py` 不直接调 LLM，也不直接执行工具，它只负责编排、上下文装配、状态持久化与崩溃恢复。

### 与项目其它模块的边界

```
        ┌───────────────┐
        │ MessageBus    │  channels / api / cron 等都向这里 publish_inbound
        └──────┬────────┘
               │ consume_inbound
               ▼
 ┌───────────────────────────────────────────────────────┐
 │ AgentLoop.run()                  L1 主循环            │
 │   ├─ priority command → inline dispatch               │
 │   ├─ deferred automation turn (cron / local trigger)  │
 │   ├─ pending queue 注入（同 session 中途消息）        │
 │   └─ _dispatch(msg) ──────────────┐                   │
 └───────────────────────────────────┼───────────────────┘
                                     ▼
 ┌───────────────────────────────────────────────────────┐
 │ _process_message(msg)             L2 状态机 driver   │
 │   RESTORE→COMPACT→COMMAND→BUILD→RUN→SAVE→RESPOND→DONE│
 │                                       │               │
 │                                       ▼               │
 │                  _run_agent_loop / AgentRunner.run    │
 │                                  L3 LLM↔tool 循环     │
 └───────────────────────────────────────────────────────┘
```

设计约束（来自 `.agent/design.md`）很明确：**核心要小，能力往边缘推**。`loop.py` 越大越说明有人把产品逻辑塞进了核心层，这是反模式。

---

## 1. 关键数据结构

### 1.1 `TurnState` / `TurnKind` (`loop.py:102-116`)

```python
class TurnState(Enum):
    RESTORE = auto()
    COMPACT = auto()
    COMMAND = auto()
    BUILD = auto()
    RUN = auto()
    SAVE = auto()
    RESPOND = auto()
    DONE = auto()

class TurnKind(Enum):
    USER = auto()      # 用户消息（来自 channel）
    SYSTEM = auto()    # 系统消息：subagent 结果、后台任务、cron 触发等
```

- `TurnState` 是 L2 状态机的全部节点，**没有分支节点**：除了 `COMMAND` 可以走 `dispatch`（继续 LLM turn）或 `shortcut`（直接结束），其它状态的下一步都唯一。
- `TurnKind` 决定 handler 内部很多分支（如 `_state_restore` 里 system 频道不打 `session_turn_started` 事件；`_state_save` 里 system 的 latency 计算口径不同）。

### 1.2 事件转换表 `_TRANSITIONS` (`loop.py:256-265`)

```python
_TRANSITIONS: dict[tuple[TurnState, str], TurnState] = {
    (TurnState.RESTORE, "ok"): TurnState.COMPACT,
    (TurnState.COMPACT, "ok"): TurnState.COMMAND,
    (TurnState.COMMAND, "dispatch"): TurnState.BUILD,
    (TurnState.COMMAND, "shortcut"): TurnState.DONE,
    (TurnState.BUILD, "ok"): TurnState.RUN,
    (TurnState.RUN, "ok"): TurnState.SAVE,
    (TurnState.SAVE, "ok"): TurnState.RESPOND,
    (TurnState.RESPOND, "ok"): TurnState.DONE,
}
```

**事件驱动 FSM**：handler 返回一个字符串事件（如 `"ok"` / `"dispatch"` / `"shortcut"`），driver 用 `(当前状态, 事件)` 查表得到下一状态。这种写法的好处是把"状态转移规则"和"状态行为"完全分离，缺点是事件是裸字符串，拼错或 handler 返回表里没有的事件会直接 `RuntimeError`（`loop.py:1409-1414`）。

### 1.3 `TurnRoute` (`loop.py:118-125`)

```python
@dataclass(frozen=True)
class TurnRoute:
    channel: str
    chat_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

**把"响应回哪里"与"消息来自哪里"解耦**。用户消息的 route 通常就是原 channel/chat_id；但 `system` 频道的 `chat_id` 用 `channel:chat_id` 编码（如 `slack:C12345:1700000000.001`），需要在 `_turn_route()` (`loop.py:595-617`) 里拆开还原。Slack 还会从 session key 反推 `thread_ts` 写进 metadata，保证回复落到原线程。

### 1.4 `StateTraceEntry` (`loop.py:127-133`)

每个状态执行完会 push 一条 trace：起止时间、耗时（ms）、返回的事件、异常标记。整个 turn 结束后 `ctx.trace` 就是一份火焰图原材料，debug 慢 turn 时极其有用。

### 1.5 `TurnContext` (`loop.py:136-185`)

**单 turn 的可变数据袋**，~30 个字段，所有 `_state_*` handler 都读写这一个对象。字段大致分四组：

| 分组 | 字段 |
|---|---|
| 输入 | `msg`, `session_key`, `kind`, `route`, `runtime`, `turn_id`, `original_user_text` |
| 上下文 | `session`, `history`, `initial_messages`, `request_context`, `runtime_context_blocks` |
| 执行结果 | `final_content`, `tools_used`, `all_messages`, `stop_reason`, `had_injections` |
| 持久化控制 | `user_persisted_early`, `save_skip`, `suppress_response`, `outbound` |
| 回调 | `on_progress`, `on_stream`, `on_stream_end`, `on_retry_wait` |
| 并发/注入 | `pending_queue`, `pending_summary` |
| Hook / scope | `hooks`, `hook_factories`, `turn_scopes`, `tools` |
| 观测 | `turn_wall_started_at`, `visible_run_started_at`, `turn_latency_ms`, `trace` |

`turn_id` 格式是 `{session_key}:{time.time_ns()}`，纳秒精度避免同 session 同纳秒碰撞。

---

## 2. 装配：`__init__` 与 `from_config`

### 2.1 `from_config` (`loop.py:447-502`)

工厂方法，把 `Config` 对象翻译成构造参数。几个值得注意的点：

- **provider 不可省**：`extra.pop("provider", None) or make_provider(config)`，允许调用方注入测试用的 mock provider。
- **preset 解析**：`config.resolve_preset()` 决定初始的 `model` 和 `context_window_tokens`，优先级低于 `extra` 里显式传入的值。
- **preset 快照加载器**：`preset_helpers.make_preset_snapshot_loader(config, provider_snapshot_loader)` 是个闭包，把"当前 preset 用哪个 provider/model/context_window"冻结成不可变快照。这是 `ModelRuntimeResolver` 工作的基础（见下）。

### 2.2 `__init__` 关键字段 (`loop.py:267-445`)

按职责分组：

**运行时快照**：
```python
self.runtime_resolver = ModelRuntimeResolver(
    LLMRuntime.capture(provider, initial_model, ...),
    model_presets=configured_presets,
    provider_snapshot_loader=...,
    preset_snapshot_loader=...,
)
```
`LLMRuntime` 是不可变值对象，包含 provider、model、context_window、generation 参数、snapshot 签名。`runtime_resolver` 负责按 preset 名解析出对应的 runtime 快照。`loop.model` / `loop.provider` / `loop.context_window_tokens` 三个 property 全部读 `runtime_resolver.runtime`，注释里反复强调"selected for **future** turn admissions"——意思是改了 preset 不会影响进行中的 turn，下一个 turn 才生效。

**核心子系统**：
- `self.context = ContextBuilder(...)` —— 构建 LLM 输入消息（system prompt、history、memory、skills、runtime context）。
- `self.sessions = SessionManager(workspace)` —— session 持久化与历史读取；`set_file_cap_archiver` 把超过文件数量上限的历史归档到 `raw_archive`。
- `self.tools = ToolRegistry()` —— 工具注册中心，**所有 session 共享一个实例**，per-session 状态通过 contextvars 传递。
- `self._file_state_store = FileStateStore()` —— per-session 的文件读写追踪（用于 read 防抖、edit 校验）。
- `self._exec_session_manager = ExecSessionManager()` —— shell 工具的会话管理。
- `self.runner = AgentRunner()` —— L3 循环的执行器。
- `self.subagents = SubagentManager(...)` —— 子 agent 派生与回收。
- `self.consolidator = Consolidator(...)` —— Dream 两阶段记忆压缩。
- `self.auto_compact = AutoCompact(...)` —— TTL 过期自动压缩。

**并发控制三件套**：
```python
self._active_tasks: dict[str, list[asyncio.Task]] = {}      # session → 活跃 task 列表
self._session_locks: dict[str, asyncio.Lock] = {}           # session → 互斥锁
self._pending_queues: dict[str, asyncio.Queue] = {}         # session → 中途消息注入队列
```
含义见 §9。

**自动化 turn 协调器**：
```python
self._deferred_automation_turns: dict[str, list[InboundMessage]] = {}
self._cron_turns = CronTurnCoordinator(...)
self._local_trigger_turns = LocalTriggerTurnCoordinator(...)
```
cron / 本地触发器触发的 turn 如果命中正在运行的 session，会被 **延后** 而不是排队抢锁，避免死锁。

**全局并发闸门**：
```python
_max = int(os.environ.get("NANOBOT_MAX_CONCURRENT_REQUESTS", "3"))
self._concurrency_gate: asyncio.Semaphore | None = (
    asyncio.Semaphore(_max) if _max > 0 else None
)
```
默认 3 个 turn 同时跑，`<=0` 关闭限制。注意这是 **跨 session** 的总并发，单 session 内部由 `_session_locks` 串行。

---

## 3. L1 主循环 `run()` (`loop.py:1018-1117`)

```python
async def run(self) -> None:
    self._running = True
    try:
        await self._connect_mcp()
        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                self.auto_compact.check_expired(...)
                continue
            except asyncio.CancelledError:
                if not self._running or task_is_cancelling():
                    raise
                logger.warning("Ignoring leaked CancelledError ...")
                continue
            ...
```

**为什么用 `wait_for(timeout=1.0)` 而不是直接 `await bus.consume_inbound()`？**
为了让 `auto_compact.check_expired` 能在 idle 期间定期执行——没有消息时每秒醒来检查过期的 session，触发压缩。这是个常见的 asyncio 模式：用超时把"被动等待"变成"主动定期轮询"。

`CancelledError` 的处理很谨慎：只有在 **非停机状态** 且 **当前 task 没在被取消** 时才吞掉，否则 re-raise。注释说明这是为了防 integration 层（Telegram/Discord 等）泄漏的取消信号把主循环搞挂。

拿到消息后，路由决策有 4 个分支（按优先级）：

### 3.1 runtime 控制 (`loop.py:1050-1051`)
```python
if await agent_context.handle_runtime_control(self, msg, self.tools):
    continue
```
处理 `/model`、`/preset`、`/context_window` 等运行时切换命令——这些必须在任何 turn 调度前生效。

### 3.2 priority command (`loop.py:1052-1057`)
```python
if self.commands.is_priority(raw):
    await self._dispatch_command_inline(msg, effective_key, raw,
                                        self.commands.dispatch_priority)
    continue
```
`/stop`、`/new` 等必须立刻执行的命令，**绕过 session lock**，直接 dispatch。否则一个慢 turn 会卡死 `/stop`。

### 3.3 deferred automation turn (`loop.py:1058-1073`)
```python
for label, coordinator in self._automation_turn_coordinators:
    if coordinator.defer_if_active(msg, session_key=effective_key, ...):
        deferred = True
        break
if deferred:
    continue
```
cron / local trigger 触发的 turn 如果命中正在跑的 session，被协调器塞进 `_deferred_automation_turns[session_key]`，等当前 turn 结束 `_publish_next_deferred_automation_turn` 再发回 bus。

### 3.4 pending queue 注入 (`loop.py:1077-1104`)
```python
if effective_key in self._pending_queues:
    # 该 session 有正在跑的 turn
    if self.commands.is_dispatchable_command(raw):
        await self._dispatch_command_inline(...)  # 命令仍然 inline
        continue
    pending_msg = msg
    ...
    self._pending_queues[effective_key].put_nowait(pending_msg)
    continue
```
**核心机制**：同 session 的下一条用户消息不会新开 task 抢锁，而是塞进正在跑的 turn 的 pending queue，由 L3 的 `_drain_pending` 在工具执行间隙注入到 LLM 上下文。这让用户可以在 agent 思考时追加信息（"对了，还要考虑 X"），而不是排队等 30 秒。

注意：命令仍然 inline dispatch，不会被注入——你不会希望 `/stop` 被塞进 LLM 上下文。

### 3.5 新建 task (`loop.py:1107-1114`)
```python
task = asyncio.create_task(self._dispatch(msg))
self._active_tasks.setdefault(effective_key, []).append(task)
task.add_done_callback(...)  # 从 _active_tasks 中移除自己
```
普通消息走的标准路径。`_active_tasks` 记录每个 session 的活跃 task 列表，`/stop` 通过它找到要取消的 task。

### 3.6 finally
```python
finally:
    await self.close_mcp()
```
`close_mcp()` (`loop.py:1279-1298`) 的顺序很讲究：先 drain `_background_tasks`（避免压缩任务写到一半被砍），再关 subagent / exec session / MCP 连接。任意一步抛异常会被收集到 `errors`，最后统一 raise（单异常直接 raise，多个异常 raise `BaseExceptionGroup`）。

---

## 4. `_dispatch(msg)` (`loop.py:1119-1277`)

单 turn 调度的 **生命周期管理器**，复杂度集中在这里。结构：

```python
async def _dispatch(self, msg):
    session_key = self._effective_session_key(msg)
    lock = self._session_locks.setdefault(session_key, asyncio.Lock())
    gate = self._concurrency_gate or nullcontext()
    pending: asyncio.Queue | None = None
    try:
        async with lock, gate:
            pending = asyncio.Queue(maxsize=20)
            self._pending_queues[session_key] = pending
            try:
                # 构造 stream 回调（如 msg.metadata["_wants_stream"]）
                response = await self._process_message(msg, ..., pending_queue=pending)
                if response is not None:
                    await self.bus.publish_outbound(response)
                ...
                # runtime event: turn_completed
                # coordinator.complete(msg, response=response)
            except asyncio.CancelledError:
                # 试图恢复 runtime checkpoint，把已完成的部分结果落到 session
                raise
            except Exception as exc:
                # 兜底错误消息 + turn_completed
            finally:
                # 把 pending queue 里没消费完的消息 re-publish 回 bus
                # runtime event: run_status_changed("idle")
                # clear_turn / publish_next_deferred_automation_turn
    finally:
        if pending is None:
            # 没拿到 lock 就被取消（极少见）也要发 idle 信号
```

### 4.1 per-session 串行 + 跨 session 并发
`async with lock, gate` 同时获取 session 互斥锁和全局并发闸门。同一个 `session_key` 的 turn 必须串行，不同 session 可以并行（最多 `_concurrency_gate` 个）。

### 4.2 pending queue 的生命周期
**只有持有 session lock 的 task 才能创建 `_pending_queues[session_key]`**，释放锁前必须 pop 掉。这保证：
- 主循环在 §3.4 看到 `_pending_queues[key]` 时，一定有一个正在跑的 turn 会消费它。
- 下一个拿到锁的 task 看到的是干净状态，不会误读到上一个 turn 的队列。

`finally` 里的清理很小心：
```python
if self._pending_queues.get(session_key) is pending:
    queue = self._pending_queues.pop(session_key, None)
else:
    queue = pending
```
**身份比较** (`is pending`) 防止误删后继 task 的 queue——理论上不会发生（锁保护），但作为防御。

### 4.3 流式回调的装配 (`loop.py:1135-1170`)
只有 `msg.metadata.get("_wants_stream")` 才装配 `on_stream` / `on_stream_end`。stream id 设计为 `{session_key}:{time_ns()}:{segment}`，`segment` 在每次 `on_stream_end` 时递增——一次 turn 内 LLM 可能多次输出（工具调用之间各一段），用 segment 区分。

### 4.4 CancelledError 的优雅处理
```python
except asyncio.CancelledError:
    ...
    try:
        session = self.sessions.get_or_create(key)
        if self._restore_runtime_checkpoint(session):
            self._clear_pending_user_turn(session)
            self.sessions.save(session)
    except Exception:
        logger.debug(...)
    raise
```
**关键设计**：用户按 `/stop` 后，turn 被取消，但 LLM 已经输出的 assistant 消息和已经完成的工具结果不会丢——它们在工具执行期间被 `_emit_checkpoint` 写到 `session.metadata["runtime_checkpoint"]`，这里调 `_restore_runtime_checkpoint` 把它们落到 `session.messages`。下次用户再发消息时，上一轮的部分成果就在历史里了。详见 §8。

### 4.5 兜底响应
```python
except Exception as exc:
    await self.bus.publish_outbound(OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id,
        content="Sorry, I encountered an error.",
    ))
```
任何未捕获异常都给用户一个统一错误回执，避免 channel 侧挂死等响应。

---

## 5. L2 状态机 driver：`_process_message` (`loop.py:1311-1422`)

```python
async def _process_message(self, msg, ...):
    ...
    ctx = TurnContext(msg=msg, state=TurnState.RESTORE, ...)
    while ctx.state is not TurnState.DONE:
        handler_name = f"_state_{ctx.state.name.lower()}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            raise RuntimeError(f"Missing state handler for {ctx.state}")
        t0 = time.perf_counter()
        try:
            event = await handler(ctx)
        except Exception:
            ctx.trace.append(StateTraceEntry(..., error="exception"))
            raise
        duration = (time.perf_counter() - t0) * 1000
        ctx.trace.append(StateTraceEntry(state=ctx.state, event=event, ...))
        next_state = self._TRANSITIONS.get((ctx.state, event))
        if next_state is None:
            raise RuntimeError(f"No transition from {ctx.state} on event {event!r}")
        ctx.state = next_state
    return ctx.outbound
```

要点：

- **反射式 dispatch**：`_state_{STATE_NAME.lower()}` 直接定位 handler，新增状态只要加一个 `_state_xxx` 方法并补 `_TRANSITIONS`。
- **trace 记录**：成功和异常都记，异常时 event 留空、error="exception"，然后 re-raise（不让 driver 吞掉业务异常）。
- **状态转移失败立刻爆炸**：handler 返回未知事件就 `RuntimeError`，避免状态机进入未定义状态后悄悄继续跑。

`_process_message` 本身不参与并发控制（不持锁），并发由调用方 `_dispatch` 保证。这让状态机逻辑很容易测试（直接 await，不需要 asyncio.Lock mock）。

---

## 6. 八个状态 handler 逐一拆解

### 6.1 `_state_restore` (`loop.py:1459-1487`)

**职责**：恢复执行前的预处理。

1. **媒体预处理**（仅 USER turn）：调 `_prepare_message_media`，把附件里的文档（PDF 等）抽出文本，或把非图片附件转成 `{{attachment: path}}` 占位符。是否抽文档文本由 `channels_config.extract_document_text` 决定。
2. **session 兜底**：理论上 caller 已建好，这里防御性 `get_or_create`。
3. **scope 持久化**：`workspace_scopes.persist_message_scope` 把这条消息带来的 workspace scope（如 webui 临时切换的 workspace）写进 session metadata。
4. **崩溃恢复**：先 `_restore_runtime_checkpoint`（恢复中断的 turn），再 `_restore_pending_user_turn`（恢复只写了 user message 就崩的 turn）。任一命中都立即 `sessions.save`。

返回 `"ok"` → `COMPACT`。

### 6.2 `_state_compact` (`loop.py:1499-1502`)

```python
async def _state_compact(self, ctx):
    ctx.session, pending = self.auto_compact.prepare_session(ctx.session, ctx.session_key)
    ctx.pending_summary = pending
    return "ok"
```

`auto_compact.prepare_session` 检查 session 是否超过 TTL 或 token 阈值，需要压缩就执行 `consolidator` 并返回 summary，原 session 被 **替换** 为压缩后的新 session。`pending_summary` 会在 BUILD 阶段作为 `session_summary` 注入 system prompt，让 LLM 知道之前聊过什么。

### 6.3 `_state_command` (`loop.py:1504-1543`)

**命令分发**。两个出口：

- **`shortcut`**：命令命中且需要短路（如 `/help`、`/new`），直接装配 `ctx.outbound`，跳到 `DONE`。
- **`dispatch`**：不是命令，或命令选择放行（如 `/model switch` 之后继续 turn），进入 `BUILD`。

shortcut 路径会提前持久化 user 消息和 assistant 响应（除了 `/new`，因为它就是用来清空 session 的），并标记 `_command=True`。这个标记在 `get_history` 时会过滤掉，**不进 LLM 上下文**——避免 `/help` 这种纯 UI 命令污染对话历史。

`is_user_turn` 的判定很细：必须是用户消息（非 system、非 subagent）、有 `original_user_text`、且不带 automation metadata。这影响 CommandContext 内部某些命令的行为分支。

### 6.4 `_state_build` (`loop.py:1545-1591`)

**装配 LLM 输入**。这是最长的一个 handler，步骤：

1. **replay 预算计算**：`replay_max_messages_for_context(ctx.runtime.context_window_tokens)` 决定历史回放多少条；`_replay_token_budget` (`loop.py:787-798`) 决定 token 上限，公式是 `context_window - max_output - 1024`，预算不足时退化到 `max(128, context_window // 2)`。
2. **token 触发的压缩**：`consolidator.maybe_consolidate_by_tokens` 在历史 token 超阈值时触发 Dream 两阶段压缩。ephemeral turn 不跑（无需持久化）。
3. **subagent 结果持久化**：subagent 回来的消息（带 `subagent_task_id`）在 prompt 组装前先落到 session，去重靠 task_id。
4. **MessageTool 重置**：每 turn 开始调 `message_tool.start_turn()`，重置"本 turn 是否发过消息"的标志。
5. **历史读取**：`session.get_history(max_messages=..., max_tokens=..., extend_to_user=...)` 按预算读历史。
6. **runtime event 记录**：`record_turn_runtime` 把本次 turn 用的 model/context_window 落到 runtime event bus。
7. **request_context 装配**：`_request_context_for_turn` 构造一个 `RequestContext`，绑定 channel/chat_id/session_key/workspace 等，**这是 contextvars 注入的材料**。
8. **runtime context blocks**（仅 USER）：`_resolve_runtime_context_for_turn` 让工具（如 weather tool 注入当前位置）和注册的 `_runtime_context_providers` 提供实时上下文块，最终拼到 user message 里。
9. **initial_messages 构建**：调 `context.build_messages`，输出 LLM API 的完整消息列表。
10. **早持久化**（仅 USER）：`_persist_user_message_early` 立即把 user 消息落盘。这一步 **至关重要**——见 §8.2。
11. **回调兜底**：`on_progress` / `on_retry_wait` 没注入就构造默认的 bus-publishing 版本。

返回 `"ok"` → `RUN`。

### 6.5 `_state_run` (`loop.py:1593-1634`)

```python
async def _state_run(self, ctx):
    if ctx.visible_run_started_at is None:
        ctx.visible_run_started_at = time.time()
    if ctx.kind is TurnKind.USER:
        await self._runtime_events().run_status_changed(
            ctx.msg, ctx.session_key, "running", started_at=ctx.visible_run_started_at,
        )
    result = await self._run_agent_loop(ctx.initial_messages, ...)
    final_content, tools_used, all_msgs, stop_reason, had_injections = result
    ctx.final_content = final_content
    ...
    if ctx.kind is TurnKind.USER:
        await turn_continuation.maybe_continue_turn(ctx)
    return "ok"
```

- 把 RUN 阶段开始的 wall clock 记到 `visible_run_started_at`（如果还没记），用于后续 latency 计算。
- USER turn 发 `run_status_changed("running")` 让 WebUI 显示 spinner。
- 调 `_run_agent_loop`（见 §7）拿到结果。
- `maybe_continue_turn`：sustained goal / 自动续算场景下，可能直接进入下一轮 `_process_message`，不再回到主循环。

### 6.6 `_state_save` (`loop.py:1636-1680`)

**持久化 turn 结果**。

1. `turn_continuation.prepare_save_boundary(ctx)`：处理续算场景下的 save 边界（哪些消息属于本 turn，哪些属于下一 turn）。
2. **空响应兜底**：USER turn 如果 `final_content` 为空且不抑制响应，填一个默认消息（`EMPTY_FINAL_RESPONSE_MESSAGE`）。
3. **latency 计算**：
   ```python
   latency_started_at = (
       ctx.visible_run_started_at
       if (SYSTEM or 内部续算) and visible_run_started_at is not None
       else ctx.turn_wall_started_at
   )
   ```
   system turn 和内部续算用 visible_run_started_at（RUN 阶段开始），普通 user turn 用 turn_wall_started_at（dispatch 开始），口径不同因为 system turn 在 RUN 之前可能有大量准备时间不计入"模型延迟"。
4. `_save_turn(...)`：把 L3 返回的 `all_messages` 写回 `session.messages`（见 §8.3）。
5. **文件数 cap**：非 ephemeral 时调 `session.enforce_file_cap`，超过上限归档老消息到 `raw_archive`。
6. **后台 token 压缩**：`_schedule_background(self.consolidator.maybe_consolidate_by_tokens(...))` —— 不阻塞响应，后台跑。
7. 清理 checkpoint / pending user turn 标志，`sessions.save`。

返回 `"ok"` → `RESPOND`。

### 6.7 `_state_respond` (`loop.py:1682-1705`)

- 抑制响应（`ctx.suppress_response`）→ outbound = None。
- SYSTEM turn → 直接构造 OutboundMessage，route 用 `ctx.route`（已经解码过 channel/chat_id）。
- USER turn → `_assemble_outbound`，处理 MessageTool 抑制、StreamedResponseEvent 装配、latency 写入 metadata。

`MessageTool` 抑制逻辑：如果本 turn agent 已经用 MessageTool 主动发过消息（`mt._sent_in_turn`），且没有注入消息或 stop_reason 不是 `empty_final_response`，就不再发 outbound——避免给用户重复消息。

返回 `"ok"` → `DONE`。

---

## 7. `_run_agent_loop`：L3 桥 (`loop.py:800-1016`)

把 `AgentRunner` 包一层，处理 contextvars 绑定、hook 构造、spec 装配。

### 7.1 contextvars 绑定 (`loop.py:922-999`)

```python
file_state_token = bind_file_states(self._file_state_store.for_session(active_session_key))
request_token = bind_request_context(request_ctx)
workspace_token = bind_workspace_scope(effective_scope)
turn_scope_stack = ExitStack()
try:
    for scope in turn_scopes or ():
        turn_scope_stack.enter_context(scope)
    hook = build_agent_turn_hook(AgentTurnHookSpec(...))
    result = await self.runner.run(AgentRunSpec(...))
finally:
    turn_scope_stack.close()
    reset_workspace_scope(workspace_token)
    reset_request_context(request_token)
    reset_file_states(file_state_token)
```

**为什么用 contextvars 而不是参数传递？**
因为 `ToolRegistry` 是 **全 loop 共享** 的单例，工具实现里要读"当前 session 的 file_state"、"当前请求的 workspace"必须通过 contextvars——这是 Python 异步并发下"线程局部变量"的等价物。绑定的 token 必须在 finally 里 reset，否则会污染下一个 turn。

`turn_scopes` 是 caller 传入的额外 context manager 列表（如某些 channel 需要在 turn 内持有 token），统一用 `ExitStack` 管理。

### 7.2 hook 装配
`build_agent_turn_hook` 把 `on_progress` / `on_stream` / `on_stream_end` 和已注册的 hooks/hook_factories 合成一个 `AgentHook`（Composite 模式），传给 runner。`on_iteration=lambda i: setattr(self, "_current_iteration", i)` 让外部能读到当前迭代数。

### 7.3 AgentRunSpec 关键字段

```python
AgentRunSpec(
    initial_messages=initial_messages,
    tools=effective_tools,
    runtime=runtime,
    max_iterations=self.max_iterations,
    max_tool_result_chars=self.max_tool_result_chars,
    hook=hook,
    ...
    checkpoint_callback=_checkpoint,           # 工具执行期持久化 checkpoint
    injection_callback=_drain_pending,          # 从 pending queue 拉新消息
    llm_timeout_s=runner_wall_llm_timeout_s(...),
    goal_active_predicate=lambda: sustained_goal_active(session.metadata) if session else False,
    goal_continue_message=_goal_continue,       # sustained goal 续算提示
    finalize_on_max_iterations=turn_continuation.should_finalize_on_max_iterations(...),
)
```

`_checkpoint` / `_drain_pending` 是 L3 与 L2 的两个关键回调：
- **`_checkpoint`**：runner 在每次工具执行完调，把当前 assistant_message + 已完成 tool_results + 未完成 tool_calls 写到 `session.metadata["runtime_checkpoint"]`。这是 §4.4 cancel 恢复的材料。
- **`_drain_pending`**：runner 在工具迭代间隙调，从 `pending_queue` 拉新消息注入 LLM 上下文。详细逻辑见 `loop.py:841-903`，亮点是 **如果没拉到消息但有 subagent 在跑，会阻塞等最多 300 秒**——让 subagent 完成事件能被本 turn 消费，而不是另开 task。

### 7.4 stop_reason 后处理 (`loop.py:1000-1016`)
```python
if result.stop_reason == "max_iterations":
    logger.warning("Max iterations ({}) reached", self.max_iterations)
    should_stream = turn_continuation.should_stream_budget_response(...)
    if on_stream and on_stream_end and should_stream:
        await on_stream(result.final_content or "")
        await on_stream_end(resuming=False)
elif result.stop_reason == "error":
    logger.error("LLM returned error: {}", (result.final_content or "")[:200])
```

撞 max_iterations 时，如果 turn 满足流式条件，把 fallback 内容手动 push 进 stream——否则 Feishu 等卡片式 channel 会留着空卡片。

---

## 8. 崩溃恢复与持久化策略

### 8.1 三种中断场景

| 场景 | 已落盘状态 | 恢复机制 |
|---|---|---|
| 正常 turn 完成 | user msg + assistant msg + tool results 全部 | 无需恢复 |
| `/stop` 或异常中断 | runtime checkpoint 写到 metadata | `_restore_runtime_checkpoint` |
| 进程崩溃前 RUN | 只有 user msg 早持久化 | `_restore_pending_user_turn` |

### 8.2 早持久化 `_persist_user_message_early` (`loop.py:664-697`)

在 BUILD 阶段（LLM 调用 **之前**）就把 user 消息写进 session，并打 `_PENDING_USER_TURN_KEY = True` 标志。这意味着即使 LLM 调用过程中进程崩了，下次启动用户消息仍然在历史里。

```python
def _persist_user_message_early(self, msg, session, ...) -> bool:
    if not turn_continuation.should_persist_user_message(msg.metadata):
        return False
    ...
    session.add_message("user", text, **extra)
    self._mark_pending_user_turn(session)
    self.sessions.save(session)
    return True
```

恢复时 `_restore_pending_user_turn` (`loop.py:1925-1943`)：如果最后一条是 user，补一条 assistant "Error: Task interrupted before a response was generated."，让 user/assistant 交替完整。`SAVE` 阶段成功后会清掉 `_PENDING_USER_TURN_KEY`（`_clear_pending_user_turn`）。

### 8.3 runtime checkpoint 恢复 (`loop.py:1844-1923`)

**写入**（`_set_runtime_checkpoint`）：runner 工具执行期间调 `_checkpoint` callback，payload 结构：
```python
{
    "assistant_message": {...},          # 当前 LLM 输出（含 tool_calls）
    "completed_tool_results": [...],     # 已完成的 tool 结果
    "pending_tool_calls": [...],          # 还没跑完的 tool_calls
}
```

**恢复**（`_restore_runtime_checkpoint`）：
1. 重组消息序列：`[assistant_message] + completed_tool_results + 占位 tool messages`。
2. **去重**：和 `session.messages` 尾部对比，用 `_checkpoint_message_key`（role+content+tool_call_id+name+tool_calls+reasoning+thinking_blocks 七元组）算最大重叠，避免重复 append。
3. 对未完成的 tool_calls，生成占位 tool message：`"Error: Task interrupted before this tool finished."`——保证 LLM 上下文里每个 tool_call 都有对应的 tool result，不会因为缺 result 让 provider 拒绝请求。
4. 清掉 checkpoint 和 pending_user_turn 标志。

### 8.4 `_save_turn` 的清洗 (`loop.py:1738-1818`)

把 L3 的 `all_messages` 落盘时有大量校验：

- **空 assistant 消息跳过**：`role=assistant` 且 content 和 tool_calls 都空，直接丢弃（注释："they poison session context"）。
- **invalid tool result 丢弃**：tool_call_id 没在已声明的 tool_calls 里、或已经 fulfilled 过，log warning 并丢弃。注释："Undeclared tool results corrupt future provider requests."——OpenAI/Claude API 对 tool_call_id 不匹配会直接报错。
- **image data URL 替换**：`data:image/...` 转成 placeholder text，避免 base64 图像数据把 session 文件撑爆。
- **超长 tool result 截断**：超过 `max_tool_result_chars` 用 `truncate_text_fn` 截断。
- **latency_ms 注入**：最后一个 assistant 消息记录本 turn latency。

`_sanitize_persisted_blocks` (`loop.py:1707-1736`) 是具体的 block 级清洗函数，user 消息和 tool result 都会过一遍（user 不截断文本，tool result 截断）。

---

## 9. 并发模型汇总

```
全局并发闸门 _concurrency_gate (默认 3)
    │
    ├── session A (lock A 持有)
    │     └── turn 1 持有 lock，pending_queue A 建立
    │           ├── 用户新消息 → put_nowait 到 pending_queue A
    │           ├── 命令 → inline dispatch (绕过 pending_queue)
    │           └── cron/local trigger turn → defer 到 _deferred_automation_turns[A]
    │
    ├── session B (lock B 持有)
    │     └── turn 2 持有 lock
    │
    └── session C idle
          └── 新消息 → _dispatch 创建 task → 等 lock
```

**三层并发控制**：

1. **跨 session 总闸门**（`_concurrency_gate`）：限制全局同时跑的 turn 数，防止过载。
2. **per-session 互斥锁**（`_session_locks`）：同 session 内严格串行，避免历史写竞争。
3. **per-turn pending queue**（`_pending_queues`）：同 session 新消息不排队，而是注入到正在跑的 turn。

**不变量**：
- `_pending_queues[key]` 存在 ⇔ 有 task 持有 `_session_locks[key]`。
- 只有 lock 持有者能创建/pop `_pending_queues[key]`。
- `_active_tasks[key]` 列表里的 task 一定在等 lock、持有 lock、或刚释放 lock（callback 还没跑）。

**延后机制**：
- automation turn (cron / local trigger) 不抢锁，命中活跃 session 就塞 `_deferred_automation_turns[key]`。
- 当前 turn 结束 `_publish_next_deferred_automation_turn(key)` 把延后的消息发回 bus，走正常路径。

---

## 10. 设计要点与不变量清单

### 10.1 解耦
- **路由 vs 执行**：`TurnRoute` 独立于 `InboundMessage`，system 频道的复杂编码集中在一个地方。
- **状态转移 vs 状态行为**：`_TRANSITIONS` 表与 `_state_*` handler 分离，新增状态代价低。
- **L2 vs L3**：`AgentLoop` 不直接调 LLM/工具，委托给 `AgentRunner`，前者只管编排。

### 10.2 健壮性
- **三层崩溃恢复**：runtime checkpoint、pending user turn、save 阶段的清洗。
- **早持久化**：user 消息在 LLM 调用前就落盘。
- **finally 必清理**：pending queue、contextvars token、MCP 连接都有显式 cleanup。
- **CancelledError 谨慎处理**：区分真正的取消和 integration 泄漏的取消信号。

### 10.3 观测性
- `StateTraceEntry` 记录每个状态耗时，turn 结束后是一份完整的执行轨迹。
- `turn_latency_ms` 注入到 outbound metadata 和最后一条 assistant 消息。
- `runtime_events()` 暴露 turn 生命周期事件（started/running/idle/completed），WebUI 实时显示。

### 10.4 阅读这个文件的建议顺序

1. 先看 §0 的三层 loop 心智模型，建立总体认知。
2. 读 `_TRANSITIONS` 表，知道状态机有哪些节点和转移。
3. 读 `TurnContext` 字段，知道 turn 内部要传递什么。
4. 跟着 `_process_message` 的 driver，按 `RESTORE → COMPACT → COMMAND → BUILD → RUN → SAVE → RESPOND` 顺序读各 `_state_*`。
5. 最后读 `_dispatch` 和 `run()`，理解并发与路由。
6. `_run_agent_loop`、崩溃恢复、`_save_turn` 是进阶内容，可以最后看。

### 10.5 可改进点（个人观察，非建议）

- `TurnContext` 字段 ~30 个，且大多在 `_state_*` 间隐式传递，可读性偏弱。可以按生命周期拆 sub-dataclass（如 `RunResult` 单独抽出），但代价是 `ctx` 不再是单一数据袋。
- `_state_*` 返回字符串 event，类型保障弱；可以用 `Literal["ok", "dispatch", "shortcut"]` 收紧。
- `_dispatch` 的 try/except/finally 三层嵌套较深，cancel 恢复逻辑可以抽到独立函数。
- 这些都是 **现状描述**，不是建议改动——核心模块的稳定优先于重构美感，这正是 `.agent/design.md` 强调的"minimal change"。

---

## 附录：关键常量与外部依赖速查

| 名称 | 位置 | 含义 |
|---|---|---|
| `_RUNTIME_CHECKPOINT_KEY` | `loop.py:251` | session.metadata 中存 runtime checkpoint 的键 |
| `_PENDING_USER_TURN_KEY` | `loop.py:252` | session.metadata 中存 pending user turn 标志的键 |
| `_MAX_INJECTIONS_PER_TURN` | `runner.py` 导入 | 单 turn 最多注入消息数（防爆炸） |
| `NANOBOT_MAX_CONCURRENT_REQUESTS` | 环境变量 | 全局并发闸门，默认 3，`<=0` 关闭 |
| `UNIFIED_SESSION_KEY` | `session/keys.py` | 统一 session 模式下的固定 key |
| `HIDDEN_HISTORY_META` | `session/history_visibility.py` | 标记某条消息不进 LLM 上下文 |
| `RUNTIME_CONTEXT_MESSAGE_META` / `RUNTIME_CONTEXT_HISTORY_META` | `runtime_context.py` | runtime context 块在 message/history 中的元数据键 |
| `EMPTY_FINAL_RESPONSE_MESSAGE` | `utils/runtime.py` | 空响应的兜底文案 |
| `turn_continuation` | `session/turn_continuation.py` | 续算相关的所有判定逻辑集中处 |
| `automation_history_overrides` | `session/automation_turns.py` | automation turn 的历史 text/extra 覆盖 |
