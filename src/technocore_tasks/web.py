from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .board import Board
from .collector import Collector
from .config import Settings
from .events import DID_RE
from .protocols import WORK_ID_RE, protocol_catalog
from .storage import Store

PACKAGE = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.database)
    board = Board(store)
    collectors = [Collector(store, settings.base_url, room) for room in settings.source_rooms]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        tasks = [asyncio.create_task(asyncio.to_thread(store.run_maintenance, 5000))]
        if settings.collector_enabled:
            tasks.extend(asyncio.create_task(c.run_forever(settings.poll_seconds)) for c in collectors)
        yield
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="Technocore Tasks", version=__version__,
        description="Read-only multi-protocol evidence view of signed Technocore work events.",
        lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
    )
    app.state.store, app.state.board, app.state.settings = store, board, settings
    app.state.collectors = collectors
    app.mount("/static", StaticFiles(directory=str(PACKAGE / "static")), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    def context(request: Request, **extra):
        return {"request": request, "version": __version__, "rooms": settings.source_rooms, **extra}

    def collection_history() -> dict:
        summary = store.collection_summary()
        gaps = store.gaps()
        return {
            **summary,
            "gaps": gaps,
            "gap_count": store.gap_count(),
            "has_unrecoverable_gap": bool(gaps),
        }

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, q: str = Query("", max_length=300), protocol: str | None = None,
             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
        tasks, pagination = board.search_page(q, protocol=protocol, page=page, page_size=page_size)
        sections = {
            "Open work": [t for t in tasks if t.normalized_state == "open"],
            "Claimed work": [t for t in tasks if t.normalized_state == "claimed"],
            "Results submitted": [t for t in tasks if t.normalized_state == "results_submitted"],
            "Attested/completed": [t for t in tasks if t.normalized_state == "attested_completed"],
            "Conflicted": [t for t in tasks if t.conflicted],
            "Partial histories": [t for t in tasks if t.partial_history],
        }
        return templates.TemplateResponse(request, "home.html",
            context(request, sections=sections, query=q, selected_protocol=protocol or "",
                    collection_history=collection_history(), pagination=pagination,
                    maintenance=store.maintenance_status()))

    @app.get("/task/{task_id}", response_class=HTMLResponse)
    def task_detail(request: Request, task_id: str, page: int = Query(1, ge=1),
                    page_size: int = Query(50, ge=1, le=200)):
        if not WORK_ID_RE.fullmatch(task_id) or (task := board.task(task_id, page=page, page_size=page_size)) is None:
            raise HTTPException(404)
        return templates.TemplateResponse(request, "task.html", context(request, task=task))

    @app.get("/ecosystem", response_class=HTMLResponse)
    def ecosystem(request: Request):
        return templates.TemplateResponse(request, "ecosystem.html", context(request))

    @app.get("/protocols", response_class=HTMLResponse)
    def protocols(request: Request):
        return templates.TemplateResponse(request, "protocols.html",
                                          context(request, protocols=protocol_catalog()))

    @app.get("/health")
    def health():
        database = store.database_health()
        maintenance = store.maintenance_status()
        return {"status": "ok" if database["available"] else "degraded", "mode": settings.mode,
                "signing": False, "source_rooms": settings.source_rooms, "database": database,
                "maintenance": maintenance, "collectors": [collector.diagnostics() for collector in collectors]}

    @app.get("/api/tasks")
    def api_tasks(q: str = Query("", max_length=300), state: str | None = None,
                  protocol: str | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(50, ge=1, le=200)):
        tasks, pagination = board.search_page(q, state, protocol, page, page_size)
        return {"tasks": [task.to_dict(detail=False) for task in tasks], "pagination": pagination}

    @app.get("/api/tasks/{task_id}")
    def api_task(task_id: str, protocol: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(50, ge=1, le=200)):
        if not WORK_ID_RE.fullmatch(task_id) or (task := board.task(task_id, protocol, page, page_size)) is None:
            raise HTTPException(404)
        return task.to_dict(detail=True)

    @app.get("/api/did/{did}/tasks")
    def api_did_tasks(did: str, page: int = Query(1, ge=1),
                      page_size: int = Query(50, ge=1, le=200)):
        if not DID_RE.fullmatch(did):
            raise HTTPException(404)
        tasks, pagination = board.did_tasks_page(did, page, page_size)
        return {"did": did, "tasks": [task.to_dict(detail=False) for task in tasks], "pagination": pagination}

    @app.get("/api/stats")
    def api_stats():
        return {**board.stats(), "maintenance": store.maintenance_status(),
                "collectors": [collector.diagnostics() for collector in collectors]}

    @app.get("/api/protocols")
    def api_protocols():
        return {"protocols": protocol_catalog()}

    return app


app = create_app()
