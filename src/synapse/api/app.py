"""Synapse HTTP API (FastAPI).

This module is optional and requires the `api` dependency group.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import JSONResponse
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Synapse HTTP API requires FastAPI. Install with: uv sync --group api"
    ) from e

from pydantic import BaseModel, Field

from synapse.client import SynapseClient
from synapse.core.models import LanguageType
from synapse.graph.connection import ConnectionError
from synapse.services.project_service import ProjectExistsError
from synapse.services.resolver_service import AmbiguousCallableError


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


class CreateProjectRequest(BaseModel):
    name: str | None = Field(default=None, description="Project name (defaults to path basename)")
    path: str = Field(..., description="Project root path on filesystem")


class ScanRequest(BaseModel):
    source_path: str | None = Field(default=None, description="Override project path for scanning")
    clear_before_scan: bool = Field(
        default=True,
        description="Clear existing project data before writing new scan results",
    )


def create_app() -> FastAPI:
    client = SynapseClient(
        ensure_schema_on_init=False,
        verify_connectivity_on_init=False,
    )

    app = FastAPI(
        title="Synapse API",
        version="0.1.0",
    )

    @app.on_event("shutdown")
    def _shutdown() -> None:
        client.close()

    def _ensure_ready() -> None:
        try:
            client.connection.verify_connectivity()
            client.ensure_schema()
        except ConnectionError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    @app.get("/health")
    def health() -> dict[str, str]:
        try:
            client.connection.verify_connectivity()
            return {"status": "ok", "neo4j": "ok"}
        except Exception as e:  # noqa: BLE001
            return {"status": "degraded", "neo4j": "unavailable", "detail": str(e)}

    @app.get("/projects")
    def list_projects(
        include_archived: bool = Query(default=False, description="Include archived projects"),
    ) -> JSONResponse:
        _ensure_ready()
        projects = client.projects.list_projects(include_archived=include_archived)
        return JSONResponse(content=_to_jsonable(projects))

    @app.post("/projects")
    def create_project(req: CreateProjectRequest) -> JSONResponse:
        _ensure_ready()
        name = req.name or Path(req.path).name
        try:
            result = client.projects.create_project(name=name, path=req.path)
            return JSONResponse(
                content={
                    "created": result.created,
                    "project": _to_jsonable(result.project),
                }
            )
        except ProjectExistsError as e:
            raise HTTPException(
                status_code=409,
                detail=_to_jsonable(e.existing_project),
            ) from e

    @app.post("/projects/{project_id}/scan")
    def scan_project(project_id: str, req: ScanRequest) -> JSONResponse:
        _ensure_ready()
        if req.source_path is None:
            project = client.projects.get_by_id(project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            source_path = project.path
        else:
            source_path = req.source_path

        result = client.scanner.scan_project(
            project_id=project_id,
            source_path=Path(source_path),
            clear_before_scan=req.clear_before_scan,
        )
        return JSONResponse(content=_to_jsonable(result))

    @app.get("/resolve/module")
    def resolve_module(
        project_id: str,
        language_type: LanguageType,
        qualified_name: str,
    ) -> JSONResponse:
        _ensure_ready()
        module = client.resolver.get_module(
            project_id=project_id,
            language_type=language_type,
            qualified_name=qualified_name,
        )
        if module is None:
            raise HTTPException(status_code=404, detail="Module not found")
        return JSONResponse(content=_to_jsonable(module))

    @app.get("/resolve/type")
    def resolve_type(
        project_id: str,
        language_type: LanguageType,
        qualified_name: str,
    ) -> JSONResponse:
        _ensure_ready()
        typ = client.resolver.get_type(
            project_id=project_id,
            language_type=language_type,
            qualified_name=qualified_name,
        )
        if typ is None:
            raise HTTPException(status_code=404, detail="Type not found")
        return JSONResponse(content=_to_jsonable(typ))

    @app.get("/resolve/callable")
    def resolve_callable(
        project_id: str,
        language_type: LanguageType,
        qualified_name: str,
        signature: str | None = None,
        limit: int = 50,
    ) -> JSONResponse:
        _ensure_ready()
        matches = client.resolver.find_callables(
            project_id=project_id,
            language_type=language_type,
            qualified_name=qualified_name,
            signature=signature,
            limit=limit,
        )
        return JSONResponse(content=_to_jsonable(matches))

    @app.get("/query/call-chain")
    def call_chain(
        callable_id: str | None = None,
        project_id: str | None = None,
        language_type: LanguageType | None = None,
        qualified_name: str | None = None,
        signature: str | None = None,
        direction: str = "both",
        max_depth: int = 5,
        page: int = 1,
        page_size: int = 100,
    ) -> JSONResponse:
        _ensure_ready()

        resolved_id = callable_id
        if resolved_id is None:
            if project_id is None or language_type is None or qualified_name is None:
                raise HTTPException(
                    status_code=400,
                    detail="Provide callable_id or (project_id, language_type, qualified_name)",
                )
            try:
                resolved = client.resolver.resolve_callable(
                    project_id=project_id,
                    language_type=language_type,
                    qualified_name=qualified_name,
                    signature=signature,
                )
            except AmbiguousCallableError as e:
                raise HTTPException(status_code=409, detail=_to_jsonable(e.matches)) from e
            if resolved is None:
                raise HTTPException(status_code=404, detail="Callable not found")
            resolved_id = resolved.id

        if direction not in ("callers", "callees", "both"):
            raise HTTPException(status_code=400, detail="Invalid direction")

        result = client.query.get_call_chain(
            callable_id=resolved_id,
            direction=direction,  # type: ignore[arg-type]
            max_depth=max_depth,
            page=page,
            page_size=page_size,
        )
        return JSONResponse(content=_to_jsonable(result))

    @app.get("/query/type-hierarchy")
    def type_hierarchy(
        type_id: str | None = None,
        project_id: str | None = None,
        language_type: LanguageType | None = None,
        qualified_name: str | None = None,
        direction: str = "both",
        page: int = 1,
        page_size: int = 100,
    ) -> JSONResponse:
        _ensure_ready()

        resolved_id = type_id
        if resolved_id is None:
            if project_id is None or language_type is None or qualified_name is None:
                raise HTTPException(
                    status_code=400,
                    detail="Provide type_id or (project_id, language_type, qualified_name)",
                )
            resolved = client.resolver.get_type(
                project_id=project_id,
                language_type=language_type,
                qualified_name=qualified_name,
            )
            if resolved is None:
                raise HTTPException(status_code=404, detail="Type not found")
            resolved_id = resolved.id

        if direction not in ("ancestors", "descendants", "both"):
            raise HTTPException(status_code=400, detail="Invalid direction")

        result = client.query.get_type_hierarchy(
            type_id=resolved_id,
            direction=direction,  # type: ignore[arg-type]
            page=page,
            page_size=page_size,
        )
        return JSONResponse(content=_to_jsonable(result))

    @app.get("/query/module-dependencies")
    def module_dependencies(
        module_id: str | None = None,
        project_id: str | None = None,
        language_type: LanguageType | None = None,
        qualified_name: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> JSONResponse:
        _ensure_ready()

        resolved_id = module_id
        if resolved_id is None:
            if project_id is None or language_type is None or qualified_name is None:
                raise HTTPException(
                    status_code=400,
                    detail="Provide module_id or (project_id, language_type, qualified_name)",
                )
            resolved = client.resolver.get_module(
                project_id=project_id,
                language_type=language_type,
                qualified_name=qualified_name,
            )
            if resolved is None:
                raise HTTPException(status_code=404, detail="Module not found")
            resolved_id = resolved.id

        result = client.query.get_module_dependencies(
            module_id=resolved_id,
            page=page,
            page_size=page_size,
        )
        return JSONResponse(content=_to_jsonable(result))

    return app

