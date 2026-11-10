"""FastAPI application for the policy analysis vertical slice."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.domain import AnalysisReport
from app.ingestion import fetch_url, read_pdf_upload
from app.service import analyse_document
from app.store import AnalysisStore

DEFAULT_DB_PATH = Path("./legal_analysis.sqlite3")
DEFAULT_RETENTION_HOURS = 24


class URLAnalysisRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


def _store_from_environment() -> AnalysisStore:
    db_path = Path(os.getenv("LEGAL_ANALYSIS_DB", str(DEFAULT_DB_PATH)))
    retention = int(os.getenv("ANALYSIS_RETENTION_HOURS", str(DEFAULT_RETENTION_HOURS)))
    return AnalysisStore(db_path, retention_hours=retention)


def create_app(store: AnalysisStore | None = None) -> FastAPI:
    """Build the app. Tests inject a temporary store instead of using the default file."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or _store_from_environment()
        app.state.store.purge_expired()
        yield

    app = FastAPI(
        title="Legal Analysis API",
        version="0.1.0",
        description=(
            "Evidence-preserving analysis of privacy policies and terms. "
            "Returns document observations and user-impact heuristics, not legal conclusions."
        ),
        lifespan=lifespan,
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "legal-analysis-api"}

    @app.post("/v1/analyses/url", response_model=AnalysisReport, status_code=201, tags=["analyses"])
    def analyse_url(request: URLAnalysisRequest) -> AnalysisReport:
        document = fetch_url(request.url)
        store: AnalysisStore = app.state.store
        return analyse_document(document, store=store, retention_hours=store.retention_hours)

    @app.post("/v1/analyses/pdf", response_model=AnalysisReport, status_code=201, tags=["analyses"])
    async def analyse_pdf(file: UploadFile = File(...)) -> AnalysisReport:
        document = await read_pdf_upload(file)
        store: AnalysisStore = app.state.store
        return analyse_document(document, store=store, retention_hours=store.retention_hours)

    @app.get("/v1/analyses/{analysis_id}", response_model=AnalysisReport, tags=["analyses"])
    def get_analysis(analysis_id: str) -> AnalysisReport:
        report = app.state.store.get(analysis_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Analysis not found or expired")
        return report

    @app.delete("/v1/analyses/{analysis_id}", status_code=204, tags=["analyses"])
    def delete_analysis(analysis_id: str) -> None:
        if not app.state.store.delete(analysis_id):
            raise HTTPException(status_code=404, detail="Analysis not found")

    return app


app = create_app()
