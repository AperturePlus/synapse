"""Integration tests for Go framework enrichers (Gin/Fiber)."""

from __future__ import annotations

from pathlib import Path

import pytest

from synapse.adapters import GoAdapter
from synapse.enrichers.fiber import FiberEnricher
from synapse.enrichers.gin import GinEnricher


@pytest.fixture
def go_web_sample_path() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "go_web_sample"


@pytest.fixture
def go_adapter() -> GoAdapter:
    return GoAdapter("test-project")


class TestGinEnricher:
    def test_enriches_gin_routes(self, go_adapter: GoAdapter, go_web_sample_path: Path) -> None:
        ir = go_adapter.analyze(go_web_sample_path)
        GinEnricher().enrich(ir, go_web_sample_path)

        ping = next(
            c
            for c in ir.callables.values()
            if c.qualified_name == "github.com/example/web/handlers.Ping"
        )
        submit = next(
            c for c in ir.callables.values() if c.qualified_name == "github.com/example/web.Submit"
        )

        assert "GET /api/ping" in ping.routes
        assert "PUT /direct" in ping.routes
        assert "POST /submit" in submit.routes
        assert "gin:route" in ping.stereotypes
        assert "gin:route" in submit.stereotypes


class TestFiberEnricher:
    def test_enriches_fiber_routes(self, go_adapter: GoAdapter, go_web_sample_path: Path) -> None:
        ir = go_adapter.analyze(go_web_sample_path)
        FiberEnricher().enrich(ir, go_web_sample_path)

        list_users = next(
            c
            for c in ir.callables.values()
            if c.qualified_name == "github.com/example/web/handlers.ListUsers"
        )
        delete_user = next(
            c
            for c in ir.callables.values()
            if c.qualified_name == "github.com/example/web.DeleteUser"
        )

        assert "GET /v1/users" in list_users.routes
        assert "PATCH /users/:id" in list_users.routes
        assert "DELETE /users/:id" in delete_user.routes
        assert "fiber:route" in list_users.stereotypes
        assert "fiber:route" in delete_user.stereotypes

