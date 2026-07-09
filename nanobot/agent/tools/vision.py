"""Vision analysis tool — routes images to a dedicated vision-capable LLM.

Self-contained extension module: this file deliberately does not modify any
core nanobot code (``loop.py``, ``schema.py``). It achieves two things via
runtime extension:

1. Registers the ``vision_analyze`` tool (auto-discovered by ToolLoader via
   pkgutil scanning). Configuration is read directly from
   ``~/.nanobot/config.json`` under ``tools.vision`` — no ToolsConfig field
   registration needed.

2. Monkey-patches ``AgentLoop._prepare_message_media`` at import time so that
   when this tool is registered, image attachments are surfaced to the brain
   agent as ``[image: /path]`` text labels instead of base64 ``image_url``
   content blocks. Non-vision brain models (e.g. deepseek-v4) cannot process
   ``image_url`` blocks; the text label tells the brain to call
   ``vision_analyze`` to see the image via the dedicated vision model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config.paths import get_media_dir
from nanobot.config_base import Base
from nanobot.security.workspace_access import current_tool_workspace
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path
from nanobot.utils.helpers import build_image_content_blocks, detect_image_mime


class VisionError(Exception):
    """Raised when an image path is missing, unreadable, or not an image."""


_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove Qwen3-style ``<think>...</think>`` reasoning spans from the answer.

    vLLM serving Qwen3-Thinking models splits output: reasoning goes into
    ``reasoning_content`` while ``content`` carries a trailing ``</think>``
    marker before the final answer. Some response shapes also inline the full
    ``<think>...</think>`` block inside ``content``. Handle both: drop complete
    spans first, then strip any leading content up to a stray ``</think>``.
    """
    cleaned = _THINK_PATTERN.sub("", text)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[-1]
    return cleaned.strip()


class VisionToolConfig(Base):
    """Configuration for the ``vision_analyze`` tool.

    Read directly from ``tools.vision`` in ``~/.nanobot/config.json`` — this
    tool does NOT register a field on ``ToolsConfig``, so no change to
    ``schema.py`` is required.
    """

    enabled: bool = False
    api_base: str | None = Field(default=None, validation_alias="apiBase")
    api_key: str | None = Field(default=None, validation_alias="apiKey", repr=False)
    model: str = "qwen3"
    extra_headers: dict[str, str] | None = Field(default=None, validation_alias="extraHeaders")
    extra_body: dict[str, Any] | None = Field(default=None, validation_alias="extraBody")
    max_images_per_call: int = Field(default=4, ge=1, le=8, validation_alias="maxImagesPerCall")
    max_tokens: int = Field(default=2048, ge=64, le=32768, validation_alias="maxTokens")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    default_prompt: str = Field(default="Describe this image in detail.", validation_alias="defaultPrompt")


_VISION_CONFIG_CACHE: VisionToolConfig | None = None


def _load_vision_config() -> VisionToolConfig:
    """Load the vision tool config directly from ``~/.nanobot/config.json``.

    Bypasses the pydantic ``ToolsConfig`` schema so we don't have to register
    a field there. Result is cached for the process lifetime — edit the config
    and restart nanobot to pick up changes.
    """
    global _VISION_CONFIG_CACHE
    if _VISION_CONFIG_CACHE is not None:
        return _VISION_CONFIG_CACHE
    config_path = Path.home() / ".nanobot" / "config.json"
    raw_vision: dict[str, Any] = {}
    if config_path.is_file():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw_vision = raw.get("tools", {}).get("vision", {}) or {}
        except (OSError, ValueError) as exc:
            logger.warning("vision: failed to read config.json: {}", exc)
    try:
        _VISION_CONFIG_CACHE = VisionToolConfig.model_validate(raw_vision)
    except Exception as exc:
        logger.warning("vision: invalid config, using defaults: {}", exc)
        _VISION_CONFIG_CACHE = VisionToolConfig()
    return _VISION_CONFIG_CACHE


@tool_parameters(
    tool_parameters_schema(
        images=ArraySchema(
            StringSchema(
                "Local path of an image file inside the workspace or nanobot media directory.",
            ),
            description=(
                "One or more image paths to analyze together. Supports PNG, JPEG, GIF, WEBP."
            ),
            min_items=1,
        ),
        prompt=StringSchema(
            "Question or instruction for the vision model. "
            "Examples: 'Extract all visible text', 'How many objects are in this image?', "
            "'Compare these two screenshots'. "
            "Defaults to tools.vision.defaultPrompt."
        ),
        max_tokens=IntegerSchema(
            "Optional override for the maximum output tokens of the vision answer.",
            minimum=64,
            maximum=32768,
        ),
        required=["images"],
    )
)
class VisionTool(Tool):
    """Analyze images via a dedicated vision LLM and return a text description.

    The brain agent calls this when it needs to "see" an image; the image bytes
    stay inside the vision model and only a text answer is returned. This keeps
    image content out of the brain's context window and lets a non-vision brain
    model (e.g. deepseek-v4) reason about images via this tool.
    """

    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return _load_vision_config().enabled

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(workspace=ctx.workspace, config=_load_vision_config())

    def __init__(self, *, workspace: str | Path, config: VisionToolConfig) -> None:
        self.workspace = Path(workspace).expanduser()
        self.config = config
        self._client: Any = None

    @property
    def name(self) -> str:
        return "vision_analyze"

    @property
    def description(self) -> str:
        return (
            "Analyze one or more images with a vision-capable LLM and return a text "
            "answer. Use this when you need to understand image content (photos, "
            "screenshots, diagrams, OCR, object counting, comparing images). "
            "Image bytes are sent only to the vision model — they do not enter "
            "this agent's context. Pass a focused prompt for best results."
        )

    @property
    def read_only(self) -> bool:
        return True

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.config.api_base:
            return None
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        self._client = OpenAICompatProvider(
            api_key=self.config.api_key,
            api_base=self.config.api_base,
            default_model=self.config.model,
            extra_headers=self.config.extra_headers,
            extra_body=self.config.extra_body,
        )
        return self._client

    def _resolve_image(self, value: str) -> Path:
        access = current_tool_workspace(self.workspace, restrict_to_workspace=True)
        workspace = access.project_path or self.workspace
        try:
            resolved = resolve_allowed_path(
                value,
                workspace=workspace,
                allowed_root=access.allowed_root,
                extra_allowed_roots=[get_media_dir()] if access.allowed_root is not None else None,
                strict=True,
            )
        except WorkspaceBoundaryError as exc:
            raise VisionError(
                "images must be inside the workspace or nanobot media directory"
            ) from exc
        except OSError as exc:
            raise VisionError(f"image not found: {value}") from exc
        if not resolved.is_file():
            raise VisionError(f"image not found: {value}")
        raw = resolved.read_bytes()
        if detect_image_mime(raw) is None:
            raise VisionError(f"unsupported image format: {value}")
        return resolved

    async def execute(
        self,
        images: list[str] | None = None,
        prompt: str | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any:
        if not images:
            return ToolResult.error("Error: images is required and must be a non-empty list")
        if len(images) > self.config.max_images_per_call:
            return ToolResult.error(
                f"Error: too many images (max {self.config.max_images_per_call})"
            )

        client = self._get_client()
        if client is None:
            return ToolResult.error(
                "Error: tools.vision.apiBase is not configured. "
                "Set tools.vision.apiBase in ~/.nanobot/config.json."
            )

        try:
            resolved = [self._resolve_image(p) for p in images]
        except VisionError as exc:
            return ToolResult.error(f"Error: {exc}")

        blocks: list[dict[str, Any]] = []
        for fp in resolved:
            raw = fp.read_bytes()
            mime = detect_image_mime(raw) or "image/png"
            blocks += build_image_content_blocks(raw, mime, str(fp), f"(Image: {fp.name})")
        blocks.append({"type": "text", "text": prompt or self.config.default_prompt})

        messages: list[dict[str, Any]] = [{"role": "user", "content": blocks}]
        try:
            response = await client.chat(
                messages=messages,
                model=self.config.model,
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=self.config.temperature,
            )
        except Exception as exc:
            logger.warning("vision_analyze call failed: {}", exc)
            return ToolResult.error(f"Error: vision model call failed: {exc}")

        text = (getattr(response, "content", None) or "").strip()
        if not text:
            return ToolResult.error("Error: vision model returned empty content")
        return _strip_thinking(text)


# ---------------------------------------------------------------------------
# Monkey-patch AgentLoop._prepare_message_media so image attachments are
# surfaced as ``[image: /path]`` text labels when this tool is registered.
# This lets a non-vision brain (deepseek-v4 etc.) route images through
# vision_analyze instead of receiving unusable image_url content blocks.
#
# Runs at module import time (ToolLoader discovers this module via pkgutil
# during AgentLoop._register_default_tools, before any message is processed).
# Idempotent — safe to import multiple times.
# ---------------------------------------------------------------------------
def _install_image_label_patch() -> None:
    from nanobot.agent.loop import AgentLoop

    if getattr(AgentLoop, "_vision_image_label_patched", False):
        return

    original = AgentLoop._prepare_message_media

    def patched(self: Any, content: str, media: list[str]) -> tuple[str, list[str]]:
        new_content, image_paths = original(self, content, media)
        if image_paths and "vision_analyze" in self.tools.tool_names:
            labels = "\n".join(f"[image: {p}]" for p in image_paths)
            new_content = f"{new_content}\n\n{labels}" if new_content else labels
            return new_content, []
        return new_content, image_paths

    AgentLoop._prepare_message_media = patched  # type: ignore[assignment]
    AgentLoop._vision_image_label_patched = True  # type: ignore[attr-defined]
    logger.debug("vision: patched AgentLoop._prepare_message_media to emit [image: path] labels")


_install_image_label_patch()
