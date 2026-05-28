# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is a lightweight, open-source AI agent framework written in Python with a React/TypeScript WebUI. It centers around a small agent loop that receives messages from chat channels, invokes an LLM provider, executes tools, and manages session memory.

## Development Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Python: run all tests / single test / lint
pytest
pytest tests/test_openai_api.py::test_function -v
ruff check nanobot/

# WebUI: dev server (proxies API/WS to gateway :8765), build, test
# Build outputs to ../nanobot/web/dist (bundled into the Python wheel)
cd webui && bun run dev      # or NANOBOT_API_URL=... bun run dev
cd webui && bun run build
cd webui && bun run test     # vitest
cd webui && bun run lint     # eslint

# Gateway
nanobot gateway
```

> **Do not run `ruff format`** — the tree predates it and running it across `nanobot/` produces a large unrelated diff that destroys git blame. Only use `ruff check` and `ruff format <files-you-changed>`.

## High-Level Architecture

### Core Data Flow

Messages flow through an async `MessageBus` (`nanobot/bus/queue.py`) that decouples chat channels from the agent core:

1. **Channels** (`nanobot/channels/`) receive messages from external platforms and publish `InboundMessage` events to the bus.
2. **`AgentLoop`** (`nanobot/agent/loop.py`) consumes inbound messages, builds context, and coordinates the turn.
3. **`AgentRunner`** (`nanobot/agent/runner.py`) handles the actual LLM conversation loop: send messages to the provider, receive tool calls, execute tools, and stream responses.
4. Responses are published as `OutboundMessage` events back to the appropriate channel.

### Key Subsystems

- **Agent Loop** (`nanobot/agent/loop.py`, `runner.py`): The core processing engine. `AgentLoop` manages session keys, hooks, and context building. `AgentRunner` executes the multi-turn LLM conversation with tool execution.
- **LLM Providers** (`nanobot/providers/`): Provider implementations (Anthropic, OpenAI-compatible, OpenAI Responses API, Azure, Bedrock, GitHub Copilot, OpenAI Codex, etc.) built on a common base (`base.py`). Includes image generation (`image_generation.py`) and audio transcription (`transcription.py`). `factory.py` and `registry.py` handle instantiation and model discovery.
- **Channels** (`nanobot/channels/`): Platform integrations (Telegram, Discord, Slack, Feishu, Matrix, WhatsApp, QQ, WeChat, WeCom, DingTalk, Email, MoChat, MS Teams, WebSocket). `manager.py` discovers and coordinates them. Channels are auto-discovered via `pkgutil` scan + entry-point plugins.
- **Tools** (`nanobot/agent/tools/`): Agent capabilities exposed to the LLM: filesystem (read/write/edit/list), shell execution (with sandbox backends), web search/fetch, MCP servers, cron, notebook editing, subagent spawning, long-running tasks / sustained goals (`long_task.py`), image generation, and self-modification. Tools are auto-discovered via `pkgutil` scan + entry-point plugins.
- **Memory** (`nanobot/agent/memory.py`): Session history persistence with Dream two-phase memory consolidation. Uses atomic writes (temp file + fsync + rename + directory fsync). Do not replace with plain `open(..., "w")` writes.
- **Session Management** (`nanobot/session/`): Per-session history, context compaction, TTL-based auto-compaction (`manager.py`), and sustained goal state tracking (`goal_state.py`).
- **Config** (`nanobot/config/schema.py`, `loader.py`): Pydantic-based configuration loaded from `~/.nanobot/config.json`. Supports camelCase aliases for JSON compatibility. `${VAR}` references in config values are resolved from environment variables at load time (no default-value syntax; missing vars raise `ValueError`).
- **Bridge** (`bridge/`): TypeScript services (e.g. WhatsApp bridge) bundled into the wheel via `pyproject.toml` `force-include`.
- **WebUI** (`webui/`): React 18 + Vite + Tailwind CSS SPA with i18next internationalization. Talks to the gateway over a WebSocket multiplex protocol. The dev server proxies `/api`, `/webui`, `/auth`, and WebSocket traffic to the gateway.
- **API Server** (`nanobot/api/server.py`): OpenAI-compatible HTTP API (`/v1/chat/completions`, `/v1/models`) for programmatic access.
- **Command Router** (`nanobot/command/`): Slash command routing and built-in command handlers.
- **Heartbeat** (`nanobot/heartbeat/`): Periodic agent wake-up using virtual tool calls (not free-text parsing). New periodic checks should follow this pattern.
- **Pairing** (`nanobot/pairing/`): DM sender approval store with persistent pairing codes per channel.
- **Skills** (`nanobot/skills/`): Built-in skill definitions (long-goal, cron, github, image-generation, etc.) as markdown + YAML frontmatter. Agent "know-how" should be added here, not hardcoded into the agent loop.
- **Security** (`nanobot/security/`): PTH file guard and other security measures activated at CLI entry.
- **Templates** (`nanobot/templates/`): Jinja2 markdown files for agent system prompts (`identity.md`, `platform_policy.md`, `SOUL.md`, etc.). Changes here alter agent behavior as directly as changing Python code.

### Entry Points

- **CLI**: `nanobot/cli/commands.py`
- **Python SDK**: `nanobot/nanobot.py`

### Extension Patterns

Providers, channels, and tools are auto-discovered via `pkgutil.walk_packages` + entry-point plugins. To add a new one:
- **Provider**: Subclass `LLMProvider` in `nanobot/providers/`, implement `_call()`. Register in `factory.py`.
- **Channel**: Subclass `BaseChannel` in `nanobot/channels/`, implement `start()`. Discovered automatically.
- **Tool**: Add to `nanobot/agent/tools/`, register via `ToolRegistry`. Discovered automatically.

### Testing

Tests live in `tests/` and mirror the `nanobot/` package structure. Key fixtures in `tests/agent/conftest.py`:
- `make_provider()` — creates a mock LLM provider
- `make_loop()` — creates a real `AgentLoop` instance for integration testing

## Design Constraints

Core architectural rules (see [`.agent/design.md`](.agent/design.md) for full rationale):
- **Core stays small; extend at the edges**: new capabilities go in `channels/`, `tools/`, skills, or MCP servers. Changes to `agent/loop.py` and `agent/runner.py` should be minimal and justified.
- **Less structure, more intelligence**: prefer simple code over new framework layers. The best fix is often a smaller prompt or tighter tool contract.
- **Prefer duplication over premature abstraction**: channels and providers may repeat similar logic. Do not introduce shared helpers just to eliminate duplication — keep each file self-contained.
- **Minimal change that solves the real problem**: do not bundle unrelated refactors into a bugfix PR.

## Security Boundaries

See [`.agent/security.md`](.agent/security.md) for full details:
- **Workspace restriction**: all filesystem tools resolve paths through `_resolve_path` (`agent/tools/filesystem.py`). New path-handling must go through this or perform an equivalent check.
- **SSRF protection**: all outbound HTTP from tools must pass through `validate_url_target` (`security/network.py`). Do not add direct `httpx.get` / `requests.get` calls.
- **Shell sandbox**: optional command wrapping via `tools/sandbox.py` (bwrap backend). New backends implement `_wrap_<name>()` and register in `_BACKENDS`.

## Branching Strategy

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full two-branch model (`main` vs `nightly`) and PR guidelines.

## Code Style

- Python 3.11+, asyncio throughout. Windows explicitly supported (use `pathlib.Path`, not `/` separators).
- Line length: 100.
- Linting: `ruff` with rules E, F, I, N, W (E501 ignored).
- pytest with `asyncio_mode = "auto"`.
- WebUI: TypeScript with ESLint, React 18, Tailwind CSS.

## Common File Locations

- Config schema: `nanobot/config/schema.py`
- Provider base / new provider template: `nanobot/providers/base.py`
- Channel base / new channel template: `nanobot/channels/base.py`
- Tool registry: `nanobot/agent/tools/registry.py`
- Prompt templates: `nanobot/templates/`
- WebUI dev proxy config: `webui/vite.config.ts`
- Tests mirror the `nanobot/` package structure.

### Fork + 双 Remote 工作流
2. 配置双 Remote
**把 origin 指向自己的 fork**
```bash
git remote rename origin upstream
git remote add origin git@github.com:lcfxybq/nanobot.git
```

```bash
#验证
git remote -v
# origin    git@github.com:lcfxybq/nanobot.git  (你的 fork，日常推送)
# upstream  git@github.com:HKUDS/nanobot.git    (原仓库，同步上游更新)
```

3. 日常开发流程

main (跟踪 upstream/main，保持同步)
 │
 └─── develop (你的开发主线，从 main 派生)
       │
       ├─── feature/xxx (功能分支)
       ├─── fix/xxx     (修复分支)
       └─── custom/xxx  (自定义定制分支)

具体操作：

```bash
# 创建你的开发主线
git checkout -b develop

# 开发新功能
git checkout -b feature/my-feature develop
# ... 开发提交 ...
git checkout develop && git merge feature/my-feature

# 推送到你的 fork
git push origin develop
```

4. 定期同步上游更新（核心）

```bash
# 拉取原作者的最新代码
git fetch upstream

# 同步到你的 main（保持干净，不带你的修改）
git checkout main
git merge upstream/main
git push origin main

# 将上游更新合入你的开发线
git checkout develop
git merge main
# 解决冲突（如果有），然后继续开发
```

5. 减少冲突的关键策略

| 策略       | 说明                                |
| -------- | --------------------------------- |
| 扩展而非修改   | 新增文件/模块优于修改原文件                    |
| 用插件/配置扩展 | 如新增 channel/provider，按项目已有的插件机制接入 |
| 改动集中管理   | 自定义改动尽量集中在少数文件，减少与上游的冲突面          |
| 定期同步     | 建议每周或每两周同步一次上游，避免积累大量冲突           |

6. 建议的分支命名规范

```text
main          → 与 upstream/main 完全同步，不直接开发
develop       → 你的开发主线
feature/*     → 新功能
fix/*         → bug 修复
custom/*      → 个人定制/实验性功能
dependabot/*  → 依赖更新
```

7. 贡献回原项目

```bash
# 从最新的 upstream/main 创建分支
git checkout -b contrib/my-fix upstream/main
# 开发 + 提交 + 推送到你的 fork
git push origin contrib/my-fix
# 然后在 GitHub 上向上游发 Pull Request
```

## others
- When making a git commit, do not include "Co-Authored-By".
- Avoid using meaningless try-except syntax
- Annotations should be written in English.
- Communication with user in Chinese
- conda activate bot
