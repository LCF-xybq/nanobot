"""Gateway HTTP routes for the agricultural algorithm panel.

NOTE: The websockets library HTTP parser only handles GET requests.
All routes must be GET; parameters are passed via query string.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from loguru import logger

from nanobot.algo.client import AlgoClient, AlgoClientError
from nanobot.algo.scenarios import SCENARIOS

if TYPE_CHECKING:
    from websockets.http11 import Request as WsRequest


def _json_response(data: Any, *, status: int = 200) -> Any:
    from websockets.datastructures import Headers
    import http
    import email.utils

    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = Headers([
        ("Date", email.utils.formatdate(usegmt=True)),
        ("Connection", "close"),
        ("Content-Length", str(len(body))),
        ("Content-Type", "application/json; charset=utf-8"),
    ])
    reason = http.HTTPStatus(status).phrase
    from websockets.http11 import Response
    return Response(status, reason, headers, body)


def _get_client(handler: Any) -> AlgoClient | None:
    return getattr(handler, "_algo_client", None)


def _query_param(request: WsRequest, name: str) -> str:
    """Extract a query parameter from the request path."""
    _, query_raw = request.path.split("?", 1) if "?" in request.path else (request.path, "")
    params = parse_qs(query_raw)
    values = params.get(name, [])
    return values[0] if values else ""


async def handle_scenarios(handler: Any, request: WsRequest) -> Any:
    scenarios = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "algorithms": [
                {"name": a.name, "display_name": a.display_name, "description": a.description}
                for a in s.algorithms
            ],
            "has_algorithms": s.has_algorithms,
        }
        for s in SCENARIOS
    ]
    return _json_response({"scenarios": scenarios})


async def handle_services(handler: Any, request: WsRequest) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    try:
        data = await client.list_services()
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


async def handle_tasks(handler: Any, request: WsRequest) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    try:
        data = await client.tasks()
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


async def handle_tasks_by_service(
    handler: Any, request: WsRequest, service_name: str,
) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    try:
        data = await client.tasks_by_service(service_name)
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


async def handle_service_status(
    handler: Any, request: WsRequest, service_name: str,
) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    try:
        data = await client.service_status(service_name)
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


async def handle_task_status(
    handler: Any, request: WsRequest, task_id: str,
) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    try:
        data = await client.task_status(task_id)
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


async def handle_start(
    handler: Any, request: WsRequest, service_name: str,
) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    filename = _query_param(request, "filename")
    if not filename:
        return _json_response({"error": "filename is required"}, status=422)
    try:
        data = await client.start_service(service_name, filename)
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


async def handle_stop(
    handler: Any, request: WsRequest, service_name: str,
) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    try:
        data = await client.stop_service(service_name)
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


async def handle_list_data(handler: Any, request: WsRequest) -> Any:
    client = _get_client(handler)
    if not client:
        return _json_response({"error": "Algorithm service not configured"}, status=503)
    algo_name = _query_param(request, "algo_name")
    if not algo_name:
        return _json_response({"error": "algo_name is required"}, status=422)
    try:
        data = await client.list_data(algo_name)
        return _json_response(data)
    except AlgoClientError as e:
        return _json_response({"error": str(e)}, status=502)


# Route matching — all GET, no method discrimination

_TASKS_BY_SERVICE_RE = re.compile(r"^/api/algo/tasks/([^/]+)$")

_ROUTES: list[tuple[str, Any]] = [
    (r"^/api/algo/scenarios$", handle_scenarios),
    (r"^/api/algo/services$", handle_services),
    (r"^/api/algo/tasks$", handle_tasks),
    (r"^/api/algo/status/([^/]+)$", handle_service_status),
    (r"^/api/algo/task/([^/]+)$", handle_task_status),
    (r"^/api/algo/start/([^/]+)$", handle_start),
    (r"^/api/algo/stop/([^/]+)$", handle_stop),
    (r"^/api/algo/data$", handle_list_data),
]


async def dispatch_algo_route(
    handler: Any, path: str, request: WsRequest,
) -> Any | None:
    """Try to match an /api/algo/* route. Returns a Response or None."""

    # Strip query string for path matching but keep original request for param extraction
    clean_path = path.split("?")[0] if "?" in path else path

    # tasks_by_service must be checked before generic /api/algo/tasks
    m = _TASKS_BY_SERVICE_RE.match(clean_path)
    if m:
        return await handle_tasks_by_service(handler, request, m.group(1))

    for pattern, handler_fn in _ROUTES:
        m = re.match(pattern, clean_path)
        if not m:
            continue
        groups = m.groups()
        if groups:
            return await handler_fn(handler, request, *groups)
        return await handler_fn(handler, request)

    return None
