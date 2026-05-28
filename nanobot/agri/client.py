"""HTTP client for the agricultural application service."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger


class AgriClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AgriClient:
    """Async client wrapping the 8 agricultural service endpoints."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = await self._client.request(method, path, json=json_body)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException as e:
            msg = f"Agricultural service timeout: {e}"
            logger.warning(msg)
            raise AgriClientError(msg) from e
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                body = e.response.json()
                detail = body.get("message", body.get("error", ""))
            except Exception:
                detail = e.response.text[:200]
            msg = f"Agricultural service error ({e.response.status_code}): {detail}"
            logger.warning(msg)
            raise AgriClientError(msg, status_code=e.response.status_code) from e
        except httpx.RequestError as e:
            msg = f"Agricultural service unreachable: {e}"
            logger.warning(msg)
            raise AgriClientError(msg) from e

    # --- 8 API endpoints ---

    async def list_services(self) -> dict[str, Any]:
        return await self._request("GET", "/list_service")

    async def start_service(self, service_name: str, filename: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/start_service/{service_name}", json_body={"filename": filename},
        )

    async def service_status(self, service_name: str) -> dict[str, Any]:
        return await self._request("GET", f"/service_status/{service_name}")

    async def task_status(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/task_status/{task_id}")

    async def tasks(self) -> dict[str, Any]:
        return await self._request("GET", "/tasks")

    async def tasks_by_service(self, service_name: str) -> dict[str, Any]:
        return await self._request("GET", f"/tasks/{service_name}")

    async def stop_service(self, service_name: str) -> dict[str, Any]:
        return await self._request("POST", f"/stop_service/{service_name}")

    async def list_data(self, agri_name: str) -> dict[str, Any]:
        return await self._request("POST", "/list_data", json_body={"algo_name": agri_name})
