"""Agent tool for invoking agricultural applications from chat."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


class AgriTool(Tool):
    """Agricultural application tool: manage crop analysis services and tasks."""

    name = "agri"
    description = (
        "Manage agricultural application tasks. Actions: "
        "'list' — list all available services;"
        "'list_data' — list input data files for an service (requires service_name);"
        "'start' — start an service task (requires service_name and filename);"
        "'status' — check running task status (requires service_name);"
        "'task' — check task status by task_id (requires task_id);"
        "'stop' — stop a running service (requires service_name); "
        "'tasks' — list all tasks, optionally filtered by service_name."
    )

    _scopes = {"core"}

    parameters = tool_parameters_schema(
        action=StringSchema(
            "Action to perform: list, list_data, start, status, task, stop, tasks",
            enum=("list", "list_data", "start", "status", "task", "stop", "tasks"),
        ),
        service_name=StringSchema("Agricultural application name (e.g. daosui, yangmiao, qiuchao, daofu, ndvi)", nullable=True),
        filename=StringSchema("MinIO data file name (required for 'start')", nullable=True),
        task_id=StringSchema("Task ID (required for 'task')", nullable=True),
        required=["action"],
    )

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        try:
            return ctx.config.algo.enabled and bool(ctx.config.algo.base_url)
        except Exception:
            return False

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(base_url=ctx.config.algo.base_url)

    def __init__(self, base_url: str):
        from nanobot.agri.client import AgriClient
        self._client = AgriClient(base_url)

    async def execute(
        self,
        action: str,
        service_name: str | None = None,
        filename: str | None = None,
        task_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if action == "list":
                data = await self._client.list_services()
                return json.dumps(data, ensure_ascii=False, indent=2)

            if action == "list_data":
                if not service_name:
                    return "Error: service_name is required for list_data action."
                data = await self._client.list_data(service_name)
                return json.dumps(data, ensure_ascii=False, indent=2)

            if action == "start":
                if not service_name:
                    return "Error: service_name is required for start action."
                if not filename:
                    return "Error: filename is required for start action. Use list_data first to find available files."
                data = await self._client.start_service(service_name, filename)
                return json.dumps(data, ensure_ascii=False, indent=2)

            if action == "status":
                if not service_name:
                    return "Error: service_name is required for status action."
                data = await self._client.service_status(service_name)
                return json.dumps(data, ensure_ascii=False, indent=2)

            if action == "task":
                if not task_id:
                    return "Error: task_id is required for task action."
                data = await self._client.task_status(task_id)
                return json.dumps(data, ensure_ascii=False, indent=2)

            if action == "stop":
                if not service_name:
                    return "Error: service_name is required for stop action."
                data = await self._client.stop_service(service_name)
                return json.dumps(data, ensure_ascii=False, indent=2)

            if action == "tasks":
                if service_name:
                    data = await self._client.tasks_by_service(service_name)
                else:
                    data = await self._client.tasks()
                return json.dumps(data, ensure_ascii=False, indent=2)

            return f"Error: unknown action '{action}'. Use one of: list, list_data, start, status, task, stop, tasks."

        except Exception as e:
            logger.warning("agricultural tool error: {}", e)
            return f"Error: {e}"
