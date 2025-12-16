"""Integration tests for PHP adapter and Laravel enricher."""

from __future__ import annotations

from pathlib import Path

import pytest

from synapse.adapters import PhpAdapter
from synapse.enrichers.laravel import LaravelEnricher


@pytest.fixture
def php_sample_path() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "php_sample"


@pytest.fixture
def php_adapter() -> PhpAdapter:
    return PhpAdapter("test-project")


class TestPhpSymbolTableBuilding:
    def test_builds_type_map(self, php_adapter: PhpAdapter, php_sample_path: Path) -> None:
        symbol_table = php_adapter.build_symbol_table(php_sample_path)

        assert "UserController" in symbol_table.type_map
        assert (
            "App.Http.Controllers.UserController" in symbol_table.type_map["UserController"]
        )

    def test_builds_callable_map(self, php_adapter: PhpAdapter, php_sample_path: Path) -> None:
        symbol_table = php_adapter.build_symbol_table(php_sample_path)

        assert "index" in symbol_table.callable_map
        assert "show" in symbol_table.callable_map


class TestPhpReferenceResolution:
    def test_creates_modules_types_and_callables(
        self, php_adapter: PhpAdapter, php_sample_path: Path
    ) -> None:
        ir = php_adapter.analyze(php_sample_path)

        module_names = [m.qualified_name for m in ir.modules.values()]
        assert "App.Http.Controllers" in module_names

        types_by_name = {t.name: t for t in ir.types.values()}
        assert "UserController" in types_by_name

        callable_qnames = {c.qualified_name for c in ir.callables.values()}
        assert "App.Http.Controllers.UserController.index" in callable_qnames
        assert "App.Http.Controllers.UserController.show" in callable_qnames


class TestLaravelRoutingEnrichment:
    def test_enriches_controller_routes(
        self, php_adapter: PhpAdapter, php_sample_path: Path
    ) -> None:
        ir = php_adapter.analyze(php_sample_path)
        LaravelEnricher().enrich(ir, php_sample_path)

        index_callable = next(
            c
            for c in ir.callables.values()
            if c.qualified_name == "App.Http.Controllers.UserController.index"
        )
        show_callable = next(
            c
            for c in ir.callables.values()
            if c.qualified_name == "App.Http.Controllers.UserController.show"
        )

        assert "GET /users" in index_callable.routes
        assert "GET /users/{id}" in show_callable.routes

