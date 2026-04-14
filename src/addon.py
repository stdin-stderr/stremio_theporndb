import asyncio
import base64
import json
import os
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.porndb import PornDBClient

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="src/templates")

PER_PAGE = 100


def _get_client() -> PornDBClient:
    api_key = os.environ.get("PORNDB_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="PORNDB_API_KEY not configured")
    return PornDBClient(api_key)


def _decode_config(config_b64: str) -> dict:
    padding = "=" * (4 - len(config_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(config_b64 + padding).decode())


def _scene_to_meta(scene: dict) -> dict:
    bg = scene.get("background") or {}
    duration = scene.get("duration")
    title = scene.get("title") or ""
    body = scene.get("description") or ""
    description = f"{title}\n\n{body}".strip() if body else title
    trailer_url = scene.get("trailer")
    raw_date = scene.get("date") or ""
    try:
        release_info = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%-d %b %Y")
    except ValueError:
        release_info = raw_date
    return {
        "id": f"tpdb_{scene['_id']}",
        "type": "movie",
        "name": title,
        "logo": (scene.get("site") or {}).get("logo") or "",
        "poster": scene.get("poster") or "",
        "background": bg.get("full") or scene.get("image") or "",
        "releaseInfo": release_info,
        "description": description,
        "links": [
            {
                "name": p["name"],
                "category": "Cast",
                "url": f"stremio:///search?search={p['name'].replace(' ', '+')}",
            }
            for p in scene.get("performers", [])
        ] + [
            {
                "name": t["name"],
                "category": "Genres",
                "url": f"stremio:///search?search={t['name'].replace(' ', '+')}",
            }
            for t in scene.get("tags", [])
        ],
        "runtime": f"{duration // 60} min" if duration else None,
        "website": scene.get("url") or "",
        "trailers": [{"source": trailer_url, "type": "Trailer"}] if trailer_url else [],
    }


def _build_manifest(site_objects: list) -> dict:
    catalogs = [
        {
            "type": "movie",
            "id": f"tpdb_{site['id']}",
            "name": site["name"],
            "extra": [
                {"name": "search"},
                {"name": "skip"},
            ],
        }
        for site in site_objects
    ]
    return {
        "id": "com.stdin-stderr.theporndb",
        "version": "1.0.0",
        "name": "ThePornDB",
        "description": "Browse scenes from ThePornDB by site",
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie"],
        "catalogs": catalogs,
        "idPrefixes": ["tpdb_"],
        "behaviorHints": {"adult": True, "configurable": True},
    }


def _parse_extras(extras_str: str) -> dict:
    parsed = parse_qs(extras_str)
    return {k: v[0] for k, v in parsed.items()}


# --- Routes ---

@app.get("/")
async def index():
    return RedirectResponse(url="/configure")


@app.get("/configure")
async def configure(request: Request):
    return templates.TemplateResponse(
        request=request, name="configure.html", context={"preselected_sites": []}
    )


@app.get("/{config_b64}/configure")
async def configure_edit(request: Request, config_b64: str):
    try:
        config = _decode_config(config_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid config")

    site_ids = config.get("sites", [])
    client = _get_client()
    results = await asyncio.gather(
        *[client.get_site(sid) for sid in site_ids], return_exceptions=True
    )
    preselected_sites = [
        {"id": r["data"]["id"], "name": r["data"]["name"]}
        for r in results
        if isinstance(r, dict) and "data" in r
    ]

    return templates.TemplateResponse(
        request=request,
        name="configure.html",
        context={"preselected_sites": preselected_sites},
    )


@app.get("/api/sites")
async def api_sites(q: str = "", page: int = 1, per_page: int = 50):
    client = _get_client()
    return await client.get_sites(page=page, per_page=per_page, q=q)


@app.get("/{config_b64}/manifest.json")
async def manifest(config_b64: str):
    try:
        config = _decode_config(config_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid config")

    site_ids = config.get("sites", [])
    client = _get_client()

    results = await asyncio.gather(
        *[client.get_site(sid) for sid in site_ids],
        return_exceptions=True,
    )
    site_objects = [
        r["data"] for r in results if isinstance(r, dict) and "data" in r
    ]

    return JSONResponse(_build_manifest(site_objects))


@app.get("/{config_b64}/catalog/movie/{catalog_id}.json")
async def catalog(config_b64: str, catalog_id: str):
    return await _catalog_handler(catalog_id, {})


@app.get("/{config_b64}/catalog/movie/{catalog_id}/{extras}.json")
async def catalog_with_extras(config_b64: str, catalog_id: str, extras: str):
    return await _catalog_handler(catalog_id, _parse_extras(extras))


async def _catalog_handler(catalog_id: str, extras: dict) -> JSONResponse:
    if not catalog_id.startswith("tpdb_"):
        raise HTTPException(status_code=400, detail="Invalid catalog id")
    try:
        site_id = int(catalog_id[len("tpdb_"):])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid catalog id")

    skip = int(extras.get("skip", 0))
    search = extras.get("search", "")
    page = skip // PER_PAGE + 1

    client = _get_client()
    if search:
        data = await client.search_scenes(site_id, search, page=page, per_page=PER_PAGE)
    else:
        data = await client.get_site_scenes(site_id, page=page, per_page=PER_PAGE)

    metas = [_scene_to_meta(s) for s in data.get("data", [])]
    return JSONResponse({"metas": metas})


@app.get("/{config_b64}/meta/movie/{meta_id}.json")
async def meta(config_b64: str, meta_id: str):
    if not meta_id.startswith("tpdb_"):
        raise HTTPException(status_code=400, detail="Invalid meta id")
    try:
        scene_id = int(meta_id[len("tpdb_"):])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid meta id")

    client = _get_client()
    data = await client.get_scene(scene_id)
    scene = data.get("data", {})

    return JSONResponse({"meta": _scene_to_meta(scene)})


@app.get("/{config_b64}/stream/movie/{meta_id}.json")
async def stream(config_b64: str, meta_id: str):
    if not meta_id.startswith("tpdb_"):
        raise HTTPException(status_code=400, detail="Invalid meta id")
    try:
        scene_id = int(meta_id[len("tpdb_"):])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid meta id")

    client = _get_client()
    data = await client.get_scene(scene_id)
    scene = data.get("data", {})

    streams = [{
        "name": "ThePornDB",
        "description": "View on ThePornDB",
        "externalUrl": f"https://theporndb.net/scenes/{scene_id}",
    }]

    if official_url := scene.get("url"):
        site_name = (scene.get("site") or {}).get("name") or "Official Site"
        domain = urlparse(official_url).netloc.removeprefix("www.")
        streams.append({
            "name": site_name,
            "description": f"Watch on {domain}",
            "externalUrl": official_url,
        })

    return JSONResponse({"streams": streams})
