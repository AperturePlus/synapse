"""Integration tests for Java adapter.

Tests the JavaAdapter's ability to parse Java source code and produce
correct IR structures including symbol table building and reference resolution.
"""

from pathlib import Path

import pytest

from synapse.adapters import JavaAdapter
from synapse.core.models import CallableKind, TypeKind, Visibility


@pytest.fixture
def java_sample_path() -> Path:
    """Path to Java sample fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "java_sample"


@pytest.fixture
def java_adapter() -> JavaAdapter:
    """Create a JavaAdapter instance."""
    return JavaAdapter("test-project")


class TestSymbolTableBuilding:
    """Tests for Phase 1: Symbol table building."""

    def test_builds_type_map(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """Symbol table should contain all type definitions."""
        symbol_table = java_adapter.build_symbol_table(java_sample_path)

        # Check types are registered
        assert "User" in symbol_table.type_map
        assert "com.example.models.User" in symbol_table.type_map["User"]

        assert "UserService" in symbol_table.type_map
        assert "com.example.services.UserService" in symbol_table.type_map["UserService"]

        assert "Animal" in symbol_table.type_map
        assert "Dog" in symbol_table.type_map
        assert "Cat" in symbol_table.type_map
        assert "Speakable" in symbol_table.type_map

    def test_builds_callable_map(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """Symbol table should contain all callable definitions."""
        symbol_table = java_adapter.build_symbol_table(java_sample_path)

        # Check methods are registered
        assert "getName" in symbol_table.callable_map
        assert "setName" in symbol_table.callable_map
        assert "createUser" in symbol_table.callable_map
        assert "speak" in symbol_table.callable_map

        # Check constructors are registered
        assert "User" in symbol_table.callable_map
        assert "Dog" in symbol_table.callable_map

    def test_handles_nested_packages(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """Symbol table should correctly handle nested package names."""
        symbol_table = java_adapter.build_symbol_table(java_sample_path)

        # Verify qualified names include full package path
        user_qualified = symbol_table.type_map.get("User", [])
        assert any("com.example.models.User" in qn for qn in user_qualified)


class TestReferenceResolution:
    """Tests for Phase 2: Reference resolution."""

    def test_creates_modules(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """IR should contain module nodes for each package."""
        ir = java_adapter.analyze(java_sample_path)

        # Find modules by qualified name
        module_names = [m.qualified_name for m in ir.modules.values()]
        assert "com.example.models" in module_names
        assert "com.example.services" in module_names
        assert "com.example.interfaces" in module_names

    def test_creates_types_with_correct_kind(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """IR should contain types with correct TypeKind."""
        ir = java_adapter.analyze(java_sample_path)

        types_by_name = {t.name: t for t in ir.types.values()}

        assert types_by_name["User"].kind == TypeKind.CLASS
        assert types_by_name["Animal"].kind == TypeKind.CLASS
        assert types_by_name["Speakable"].kind == TypeKind.INTERFACE

    def test_resolves_extends_relationship(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """IR should resolve extends relationships between types."""
        ir = java_adapter.analyze(java_sample_path)

        types_by_name = {t.name: t for t in ir.types.values()}
        dog_type = types_by_name["Dog"]
        animal_type = types_by_name["Animal"]

        # Dog should extend Animal
        assert len(dog_type.extends) > 0
        assert animal_type.id in dog_type.extends

    def test_resolves_implements_relationship(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """IR should resolve implements relationships between types."""
        ir = java_adapter.analyze(java_sample_path)

        types_by_name = {t.name: t for t in ir.types.values()}
        cat_type = types_by_name["Cat"]
        speakable_type = types_by_name["Speakable"]

        # Cat should implement Speakable
        assert len(cat_type.implements) > 0
        assert speakable_type.id in cat_type.implements

    def test_creates_callables_with_correct_kind(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """IR should contain callables with correct CallableKind."""
        ir = java_adapter.analyze(java_sample_path)

        callables_by_name = {}
        for c in ir.callables.values():
            if c.name not in callables_by_name:
                callables_by_name[c.name] = []
            callables_by_name[c.name].append(c)

        # Constructors
        user_constructors = [
            c for c in callables_by_name.get("User", [])
            if c.kind == CallableKind.CONSTRUCTOR
        ]
        assert len(user_constructors) > 0

        # Methods
        get_name_methods = [
            c for c in callables_by_name.get("getName", [])
            if c.kind == CallableKind.METHOD
        ]
        assert len(get_name_methods) > 0

    def test_extracts_visibility(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """IR should correctly extract visibility modifiers."""
        ir = java_adapter.analyze(java_sample_path)

        callables_by_qname = {c.qualified_name: c for c in ir.callables.values()}

        # Public method
        get_name = callables_by_qname.get("com.example.models.User.getName")
        assert get_name is not None
        assert get_name.visibility == Visibility.PUBLIC

        # Private method
        bark = callables_by_qname.get("com.example.models.Dog.bark")
        assert bark is not None
        assert bark.visibility == Visibility.PRIVATE

    def test_marks_unresolved_references(
        self, java_adapter: JavaAdapter, java_sample_path: Path
    ) -> None:
        """IR should mark references that cannot be resolved."""
        ir = java_adapter.analyze(java_sample_path)

        # System.out.println calls should be unresolved
        assert len(ir.unresolved) > 0

        # Check that unresolved references have required fields
        for unresolved in ir.unresolved:
            assert unresolved.source_callable
            assert unresolved.target_name
            assert unresolved.reason


class TestDeterministicIds:
    """Tests for deterministic ID generation."""

    def test_same_input_produces_same_ids(
        self, java_sample_path: Path
    ) -> None:
        """Same source code should produce same IDs across multiple runs."""
        adapter1 = JavaAdapter("test-project")
        adapter2 = JavaAdapter("test-project")

        ir1 = adapter1.analyze(java_sample_path)
        ir2 = adapter2.analyze(java_sample_path)

        # Module IDs should match
        assert set(ir1.modules.keys()) == set(ir2.modules.keys())

        # Type IDs should match
        assert set(ir1.types.keys()) == set(ir2.types.keys())

        # Callable IDs should match
        assert set(ir1.callables.keys()) == set(ir2.callables.keys())

    def test_different_projects_produce_different_ids(
        self, java_sample_path: Path
    ) -> None:
        """Different project IDs should produce different entity IDs."""
        adapter1 = JavaAdapter("project-a")
        adapter2 = JavaAdapter("project-b")

        ir1 = adapter1.analyze(java_sample_path)
        ir2 = adapter2.analyze(java_sample_path)

        # IDs should be different
        assert set(ir1.modules.keys()) != set(ir2.modules.keys())
        assert set(ir1.types.keys()) != set(ir2.types.keys())
