"""Integration tests for Go adapter.

Tests the GoAdapter's ability to parse Go source code and produce
correct IR structures including symbol table building and reference resolution.
"""

from pathlib import Path

import pytest

from synapse.adapters import GoAdapter
from synapse.core.models import CallableKind, TypeKind, Visibility


@pytest.fixture
def go_sample_path() -> Path:
    """Path to Go sample fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "go_sample"


@pytest.fixture
def go_adapter() -> GoAdapter:
    """Create a GoAdapter instance."""
    return GoAdapter("test-project")


class TestSymbolTableBuilding:
    """Tests for Phase 1: Symbol table building."""

    def test_reads_module_name_from_go_mod(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """Should read module name from go.mod file."""
        go_adapter.build_symbol_table(go_sample_path)
        assert go_adapter._module_name == "github.com/example/sample"

    def test_builds_type_map(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """Symbol table should contain all type definitions."""
        symbol_table = go_adapter.build_symbol_table(go_sample_path)

        assert "User" in symbol_table.type_map
        assert "github.com/example/sample.User" in symbol_table.type_map["User"]

        assert "Animal" in symbol_table.type_map
        assert "Dog" in symbol_table.type_map
        assert "Cat" in symbol_table.type_map
        assert "UserService" in symbol_table.type_map

    def test_builds_callable_map(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """Symbol table should contain all callable definitions."""
        symbol_table = go_adapter.build_symbol_table(go_sample_path)

        # Functions
        assert "NewUser" in symbol_table.callable_map
        assert "NewUserService" in symbol_table.callable_map

        # Methods
        assert "GetName" in symbol_table.callable_map
        assert "SetName" in symbol_table.callable_map
        assert "Bark" in symbol_table.callable_map
        assert "Meow" in symbol_table.callable_map

    def test_handles_subpackages(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """Symbol table should correctly handle subpackages."""
        symbol_table = go_adapter.build_symbol_table(go_sample_path)

        # Types in models subpackage
        animal_qualified = symbol_table.type_map.get("Animal", [])
        assert any("models" in qn for qn in animal_qualified)

    def test_registers_modules(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """Symbol table should register all modules."""
        symbol_table = go_adapter.build_symbol_table(go_sample_path)

        assert "github.com/example/sample" in symbol_table.module_map
        assert "github.com/example/sample/models" in symbol_table.module_map


class TestReferenceResolution:
    """Tests for Phase 2: Reference resolution."""

    def test_creates_modules(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """IR should contain module nodes for each package."""
        ir = go_adapter.analyze(go_sample_path)

        module_names = [m.qualified_name for m in ir.modules.values()]
        assert "github.com/example/sample" in module_names
        assert "github.com/example/sample/models" in module_names

    def test_creates_types_with_correct_kind(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """IR should contain types with correct TypeKind."""
        ir = go_adapter.analyze(go_sample_path)

        types_by_name = {t.name: t for t in ir.types.values()}

        assert types_by_name["User"].kind == TypeKind.STRUCT
        assert types_by_name["Animal"].kind == TypeKind.STRUCT
        assert types_by_name["Dog"].kind == TypeKind.STRUCT

    def test_resolves_embeds_relationship(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """IR should resolve struct embedding relationships."""
        ir = go_adapter.analyze(go_sample_path)

        types_by_name = {t.name: t for t in ir.types.values()}
        dog_type = types_by_name["Dog"]
        cat_type = types_by_name["Cat"]
        animal_type = types_by_name["Animal"]

        # Dog and Cat should embed Animal
        assert len(dog_type.embeds) > 0
        assert animal_type.id in dog_type.embeds

        assert len(cat_type.embeds) > 0
        assert animal_type.id in cat_type.embeds

    def test_creates_functions_and_methods(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """IR should distinguish between functions and methods."""
        ir = go_adapter.analyze(go_sample_path)

        callables_by_name: dict[str, list] = {}
        for c in ir.callables.values():
            if c.name not in callables_by_name:
                callables_by_name[c.name] = []
            callables_by_name[c.name].append(c)

        # Functions (no receiver)
        new_user_funcs = callables_by_name.get("NewUser", [])
        assert len(new_user_funcs) > 0
        assert new_user_funcs[0].kind == CallableKind.FUNCTION

        # Methods (with receiver)
        get_name_methods = callables_by_name.get("GetName", [])
        assert len(get_name_methods) > 0
        assert all(m.kind == CallableKind.METHOD for m in get_name_methods)

    def test_extracts_visibility(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """IR should correctly extract visibility based on naming convention."""
        ir = go_adapter.analyze(go_sample_path)

        callables_by_name = {c.name: c for c in ir.callables.values()}

        # Exported (uppercase)
        assert callables_by_name["NewUser"].visibility == Visibility.PUBLIC
        assert callables_by_name["GetName"].visibility == Visibility.PUBLIC

    def test_links_methods_to_types(
        self, go_adapter: GoAdapter, go_sample_path: Path
    ) -> None:
        """Methods should be linked to their receiver types."""
        ir = go_adapter.analyze(go_sample_path)

        types_by_name = {t.name: t for t in ir.types.values()}
        user_type = types_by_name["User"]

        # User should have methods
        assert len(user_type.callables) > 0

        # Check that GetName is in User's callables
        callable_names = [
            ir.callables[cid].name
            for cid in user_type.callables
            if cid in ir.callables
        ]
        assert "GetName" in callable_names
        assert "SetName" in callable_names


class TestDeterministicIds:
    """Tests for deterministic ID generation."""

    def test_same_input_produces_same_ids(self, go_sample_path: Path) -> None:
        """Same source code should produce same IDs across multiple runs."""
        adapter1 = GoAdapter("test-project")
        adapter2 = GoAdapter("test-project")

        ir1 = adapter1.analyze(go_sample_path)
        ir2 = adapter2.analyze(go_sample_path)

        assert set(ir1.modules.keys()) == set(ir2.modules.keys())
        assert set(ir1.types.keys()) == set(ir2.types.keys())
        assert set(ir1.callables.keys()) == set(ir2.callables.keys())

    def test_different_projects_produce_different_ids(
        self, go_sample_path: Path
    ) -> None:
        """Different project IDs should produce different entity IDs."""
        adapter1 = GoAdapter("project-a")
        adapter2 = GoAdapter("project-b")

        ir1 = adapter1.analyze(go_sample_path)
        ir2 = adapter2.analyze(go_sample_path)

        assert set(ir1.modules.keys()) != set(ir2.modules.keys())
        assert set(ir1.types.keys()) != set(ir2.types.keys())
