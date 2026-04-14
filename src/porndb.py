import logging
import time

import httpx

BASE_URL = "https://api.theporndb.net"

_log = logging.getLogger(__name__)


class PornDBClient:
    def __init__(self, api_key: str):
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient() as client:
            t0 = time.monotonic()
            response = await client.get(
                f"{BASE_URL}{path}",
                headers=self._headers,
                params=params or {},
                timeout=30.0,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            response.raise_for_status()
            _log.debug("%s %s %s %.0fms", response.request.method, response.request.url, response.status_code, elapsed_ms)
            return response.json()

    async def get_sites(self, page: int = 1, per_page: int = 50, q: str = "") -> dict:
        params: dict = {"page": page, "per_page": per_page}
        if q:
            params["q"] = q
        return await self._get("/sites", params)

    async def get_site(self, site_id: int) -> dict:
        return await self._get(f"/sites/{site_id}")

    async def get_site_scenes(
        self, site_id: int, page: int = 1, per_page: int = 100
    ) -> dict:
        return await self._get(
            f"/sites/{site_id}/scenes", {"page": page, "per_page": per_page}
        )

    async def search_scenes(
        self, site_id: int, q: str, page: int = 1, per_page: int = 100
    ) -> dict:
        return await self._get(
            "/scenes",
            {"site_id": site_id, "q": q, "page": page, "per_page": per_page},
        )

    async def get_scene(self, scene_id: str) -> dict:
        return await self._get(f"/scenes/{scene_id}")

    async def get_performers(self, q: str = "", page: int = 1, per_page: int = 100) -> dict:
        params: dict = {"page": page, "per_page": per_page}
        if q:
            params["q"] = q
        return await self._get("/performers", params)

    async def get_performer(self, performer_id: int) -> dict:
        return await self._get(f"/performers/{performer_id}")
