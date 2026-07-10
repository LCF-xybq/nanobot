"""Compress a local folder into a zip and upload it to MinIO.

Self-contained extension module (mirrors ``vision.py``): no edit to
``nanobot/config/schema.py`` or ``nanobot/agent/loop.py``. Configuration is
read directly from ``~/.nanobot/config.json`` under ``tools.minio_upload``.

The minio SDK is imported lazily inside ``execute`` so that tool registration
does not require the dependency. Install it in the bot env::

    pip install minio
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.config_base import Base


class UploadMinioError(Exception):
    """Raised when path resolution, compression, or upload fails."""


class MinioUploadConfig(Base):
    """Configuration for the ``upload_minio`` tool under ``tools.minio_upload``."""

    enabled: bool = False
    endpoint: str | None = Field(default=None, validation_alias="endpoint")
    access_key: str | None = Field(default=None, validation_alias="accessKey", repr=False)
    secret_key: str | None = Field(default=None, validation_alias="secretKey", repr=False)
    bucket_name: str = Field(default="cloud-bucket", validation_alias="bucketName")
    secure: bool = False
    # Object key template — ``{algo}`` is filled with the ``algo`` argument,
    # ``{zip_name}`` with ``{folder}_{timestamp}.zip``. The ``algorithm`` prefix
    # must match the server-side bucket layout the algo service scans.
    object_prefix: str = Field(default="algorithm/{algo}/", validation_alias="objectPrefix")
    keep_local: bool = Field(default=False, validation_alias="keepLocal")


_MINIO_CONFIG_CACHE: MinioUploadConfig | None = None


def _load_minio_config() -> MinioUploadConfig:
    """Load the minio_upload tool config directly from ``~/.nanobot/config.json``.

    Bypasses the pydantic ``ToolsConfig`` schema so we don't have to register
    a field there. Result is cached for the process lifetime — edit the
    config and restart nanobot to pick up changes.
    """
    global _MINIO_CONFIG_CACHE
    if _MINIO_CONFIG_CACHE is not None:
        return _MINIO_CONFIG_CACHE
    config_path = Path.home() / ".nanobot" / "config.json"
    raw_block: dict[str, Any] = {}
    if config_path.is_file():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw_block = raw.get("tools", {}).get("minio_upload", {}) or {}
        except (OSError, ValueError) as exc:
            logger.warning("minio_upload: failed to read config.json: {}", exc)
    try:
        _MINIO_CONFIG_CACHE = MinioUploadConfig.model_validate(raw_block)
    except Exception as exc:
        logger.warning("minio_upload: invalid config, using defaults: {}", exc)
        _MINIO_CONFIG_CACHE = MinioUploadConfig()
    return _MINIO_CONFIG_CACHE


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema(
            "Absolute or workspace-relative path of the folder to compress and upload.",
        ),
        algo=StringSchema(
            "Algorithm name used as the MinIO object prefix (e.g. daosui, yangmiao, qiuchao). "
            "The zip is uploaded under ``algoritm/{algo}/``.",
        ),
        required=["path", "algo"],
    )
)
class UploadMinioTool(Tool):
    """Compress a folder into a zip and upload it to MinIO.

    Workflow: validate path -> zip in a temp dir -> upload to
    ``algoritm/{algo}/{folder}_{timestamp}.zip`` -> remove the temp zip.
    Returns the MinIO object name on success.
    """

    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        cfg = _load_minio_config()
        return cfg.enabled and bool(cfg.endpoint)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(workspace=ctx.workspace, config=_load_minio_config())

    def __init__(self, *, workspace: str | Path, config: MinioUploadConfig) -> None:
        self.workspace = Path(workspace).expanduser()
        self.config = config

    @property
    def name(self) -> str:
        return "upload_minio"

    @property
    def description(self) -> str:
        return (
            "Compress a local folder into a zip and upload it to MinIO under "
            "``algoritm/{algo}/``. Use this to push a dataset folder for a "
            "specific algorithm (e.g. upload /path/to/daosui_images for the "
            "'daosui' algorithm). Returns the MinIO object name."
        )

    @property
    def read_only(self) -> bool:
        return False

    def _resolve_folder(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = (self.workspace / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.exists():
            raise UploadMinioError(f"folder not found: {value}")
        if not candidate.is_dir():
            raise UploadMinioError(f"not a directory: {value}")
        if not os.access(candidate, os.R_OK):
            raise UploadMinioError(f"folder not readable: {value}")
        return candidate

    def _compress_folder(self, folder: Path, zip_path: Path) -> None:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for root, _dirs, files in os.walk(folder):
                for fname in files:
                    file_path = Path(root) / fname
                    arcname = os.path.relpath(file_path, folder)
                    archive.write(file_path, arcname=arcname)

    def _object_name(self, algo: str, zip_name: str) -> str:
        prefix = self.config.object_prefix.format(algo=algo)
        return f"{prefix}{zip_name}"

    async def execute(self, path: str | None = None, algo: str | None = None, **kwargs: Any) -> Any:
        if not path:
            return ToolResult.error("Error: path is required")
        if not algo:
            return ToolResult.error("Error: algo is required")
        algo = algo.strip()
        if not algo:
            return ToolResult.error("Error: algo must not be empty")

        try:
            from minio import Minio
            from minio.error import S3Error
        except ImportError:
            return ToolResult.error(
                "Error: minio SDK not installed. Run `pip install minio` in the bot env."
            )

        cfg = self.config
        if not cfg.endpoint:
            return ToolResult.error(
                "Error: tools.minio_upload.endpoint is not configured. "
                "Set tools.minio_upload in ~/.nanobot/config.json."
            )

        try:
            folder = self._resolve_folder(path)
        except UploadMinioError as exc:
            return ToolResult.error(f"Error: {exc}")

        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        zip_name = f"{folder.name}_{timestamp}.zip"
        object_name = self._object_name(algo, zip_name)

        try:
            client = Minio(
                endpoint=cfg.endpoint,
                access_key=cfg.access_key,
                secret_key=cfg.secret_key,
                secure=cfg.secure,
            )
            if not client.bucket_exists(cfg.bucket_name):
                client.make_bucket(cfg.bucket_name)
        except Exception as exc:
            logger.warning("upload_minio: minio connect failed: {}", exc)
            return ToolResult.error(f"Error: minio connect failed: {exc}")

        # Skip upload if the object already exists (idempotent re-runs).
        try:
            client.stat_object(cfg.bucket_name, object_name)
            return f"Object already exists in MinIO: {cfg.bucket_name}/{object_name}"
        except S3Error:
            pass

        with tempfile.NamedTemporaryFile(
            prefix=f"{folder.name}_", suffix=".zip", delete=False
        ) as tmp:
            zip_path = Path(tmp.name)
        try:
            try:
                self._compress_folder(folder, zip_path)
            except (OSError, zipfile.BadZipFile) as exc:
                return ToolResult.error(f"Error: compress failed: {exc}")

            size = zip_path.stat().st_size
            try:
                with zip_path.open("rb") as fp:
                    client.put_object(
                        bucket_name=cfg.bucket_name,
                        object_name=object_name,
                        data=fp,
                        length=size,
                    )
            except Exception as exc:
                logger.warning("upload_minio: upload failed: {}", exc)
                return ToolResult.error(f"Error: upload failed: {exc}")
        finally:
            if not cfg.keep_local and zip_path.exists():
                zip_path.unlink()

        return f"Uploaded to MinIO: {cfg.bucket_name}/{object_name} ({size} bytes)"
