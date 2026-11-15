from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import router
from .config import settings
from .seed import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("marsx")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="MARS-X API",
    version="1.0.0",
    description="Planetary exploration and mission-planning backend. Coordinates are planetocentric latitude / "
                "east-positive longitude on the IAU 2000 Mars sphere (r = 3,396,190 m); elevations are metres above the MOLA areoid.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Overlay-BBox"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    t = time.perf_counter()
    response = await call_next(request)
    log.info("%s %s -> %s in %.0f ms", request.method, request.url.path, response.status_code, (time.perf_counter() - t) * 1000)
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": {"error": "internal_error", "message": "Unexpected server error; see server logs."}})


app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {"name": "MARS-X API", "docs": "/docs", "health": "/api/v1/health"}
