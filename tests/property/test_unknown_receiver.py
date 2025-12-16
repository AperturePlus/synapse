"""Property tests for unknown receiver type handling.

**Feature: improved-call-resolution**

Tests that verify method calls on variables with unknown types are properly
recorded as unresolved references.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings, strategies as st

from synapse.adapters.go.scanner import GoScanner
from synapse.adapters.go.resolver import GoResolver
from synapse.core.models import LanguageType
from synapse.adapters.base import generate_entity_id

import tree_sitter_go as ts_go
from tree_sitter import Language, Parser


def _create_parser() -> Parser:
    """Create a tree-sitter parser for Go."""
    parser = Parser(Language(ts_go.language()))
    return parser


def _id_generator(qualified_name: str, signature: str | None = None) -> str:
    """Generate entity ID for testing."""
    return generate_entity_id("test-project", LanguageType.GO, qualified_name, signature)


# Strategies for generating Go identifiers
go_func_names = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,15}", fullmatch=True)
go_method_names = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,10}", fullmatch=True)
go_var_names = st.from_regex(r"[a-z][a-zA-Z0-9]{0,10}", fullmatch=True)


def _build_go_caller_with_unknown_receiver_call(
    caller_name: str, var_name: str, method_name: str
) -> str:
    """Build Go source code with a caller that invokes a method on an unknown variable.

    The variable is declared but its type cannot be inferred (e.g., from external package).
    """
    return f"""package main

import "external/pkg"

func {caller_name}() {{
    {var_name} := pkg.GetSomething()
    {var_name}.{method_name}()
}}
"""


def _build_go_caller_with_undeclared_var_call(
    caller_name: str, var_name: str, method_name: str
) -> str:
    """Build Go source code with a caller that invokes a method on an undeclared variable.

    This simulates a case where the variable is not in local scope.
    """
    return f"""package main

func {caller_name}() {{
    // {var_name} is not declared, simulating unknown receiver
    _ = {var_name}.{method_name}()
}}
"""


def _build_go_caller_with_interface_var_call(
    caller_name: str, var_name: str, method_name: str
) -> str:
    """Build Go source code with a caller that invokes a method on an interface{} variable.

    The variable type is interface{} which doesn't have specific methods.
    """
    return f"""package main

func {caller_name}(v interface{{}}) {{
    // v is interface{{}}, method resolution should fail
    v.({var_name}Type).{method_name}()
}}
"""


@given(
    caller_name=go_func_names,
    var_name=go_var_names,
    method_name=go_method_names,
)
@settings(max_examples=100)
def test_unknown_receiver_produces_unresolved(
    caller_name: str, var_name: str, method_name: str
) -> None:
    """
    **Feature: improved-call-resolution, Property 2: Unknown receiver produces unresolved**
    **Validates: Requirements 1.2, 3.3**

    For any method call on a variable whose type cannot be determined (e.g., from
    external package), the call SHALL be recorded as unresolved (not resolved to
    an arbitrary candidate).
    """
    source_code = _build_go_caller_with_unknown_receiver_call(
        caller_name, var_name, method_name
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create go.mod
        go_mod_path = Path(tmpdir) / "go.mod"
        go_mod_path.write_text("module testmodule\n")

        # Create source file
        source_path = Path(tmpdir) / "main.go"
        source_path.write_text(source_code)

        # Phase 1: Scan to build symbol table
        parser = _create_parser()
        scanner = GoScanner(parser, _id_generator)
        symbol_table = scanner.scan_directory(Path(tmpdir))

        # Phase 2: Resolve references
        resolver = GoResolver(parser, "test-project", LanguageType.GO, _id_generator)
        ir = resolver.resolve_directory(Path(tmpdir), symbol_table, "testmodule")

        # Find the caller function
        caller_qualified = f"testmodule.{caller_name}"
        caller_id = _id_generator(caller_qualified, "()")

        # The caller should exist in IR
        assert caller_id in ir.callables, f"Caller function not found in IR"
        caller = ir.callables[caller_id]

        # The method call should NOT be resolved to any callable
        # (since the receiver type is unknown from external package)
        # It should either be unresolved or not in calls list

        # Check that no arbitrary callable was picked
        # The method_name should not appear in any resolved call
        resolved_method_calls = [
            call_id for call_id in caller.calls
            if method_name in call_id  # Rough check - method name in ID
        ]

        # If there are resolved calls with this method name, they should be
        # from the symbol table (which is empty for this method)
        # So we expect no resolved calls for this method
        assert len(resolved_method_calls) == 0, (
            f"Method {method_name} should not be resolved when receiver type is unknown. "
            f"Found resolved calls: {resolved_method_calls}"
        )


@st.composite
def distinct_names_strategy(draw: st.DrawFn) -> tuple[str, str, str]:
    """Generate distinct caller_name, method_name, and type_name."""
    # Use different prefixes to ensure names don't collide
    caller_name = "Caller" + draw(st.from_regex(r"[A-Z][a-zA-Z0-9]{0,8}", fullmatch=True))
    method_name = "Method" + draw(st.from_regex(r"[A-Z][a-zA-Z0-9]{0,8}", fullmatch=True))
    type_name = "Type" + draw(st.from_regex(r"[A-Z][a-zA-Z0-9]{0,8}", fullmatch=True))
    return (caller_name, method_name, type_name)


@given(names=distinct_names_strategy())
@settings(max_examples=100)
def test_known_receiver_resolves_correctly(
    names: tuple[str, str, str],
) -> None:
    """
    **Feature: improved-call-resolution, Property 2: Unknown receiver produces unresolved**
    **Validates: Requirements 1.1, 1.2**

    For any method call on a variable with a known type (defined in the same module),
    the call SHALL be resolved to the correct method on that type.
    """
    caller_name, method_name, type_name = names

    # Build source with a type and method that ARE defined
    source_code = f"""package main

type {type_name} struct {{}}

func (r *{type_name}) {method_name}() {{
}}

func {caller_name}() {{
    obj := &{type_name}{{}}
    obj.{method_name}()
}}
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create go.mod
        go_mod_path = Path(tmpdir) / "go.mod"
        go_mod_path.write_text("module testmodule\n")

        # Create source file
        source_path = Path(tmpdir) / "main.go"
        source_path.write_text(source_code)

        # Phase 1: Scan to build symbol table
        parser = _create_parser()
        scanner = GoScanner(parser, _id_generator)
        symbol_table = scanner.scan_directory(Path(tmpdir))

        # Phase 2: Resolve references
        resolver = GoResolver(parser, "test-project", LanguageType.GO, _id_generator)
        ir = resolver.resolve_directory(Path(tmpdir), symbol_table, "testmodule")

        # Find the caller function
        caller_qualified = f"testmodule.{caller_name}"
        caller_id = _id_generator(caller_qualified, "()")

        assert caller_id in ir.callables, f"Caller function not found in IR"
        caller = ir.callables[caller_id]

        # The method should be resolved correctly
        method_qualified = f"testmodule.{type_name}.{method_name}"
        expected_callee_id = _id_generator(method_qualified, "()")

        assert expected_callee_id in caller.calls, (
            f"Expected method {method_qualified} to be resolved. "
            f"Caller calls: {caller.calls}"
        )


@st.composite
def distinct_names_with_var_strategy(draw: st.DrawFn) -> tuple[str, str, str, str]:
    """Generate distinct caller_name, method_name, type_name, and var_name."""
    # Use different prefixes to ensure names don't collide
    caller_name = "Caller" + draw(st.from_regex(r"[A-Z][a-zA-Z0-9]{0,8}", fullmatch=True))
    method_name = "Method" + draw(st.from_regex(r"[A-Z][a-zA-Z0-9]{0,8}", fullmatch=True))
    type_name = "Type" + draw(st.from_regex(r"[A-Z][a-zA-Z0-9]{0,8}", fullmatch=True))
    var_name = "var" + draw(st.from_regex(r"[a-z][a-zA-Z0-9]{0,8}", fullmatch=True))
    return (caller_name, method_name, type_name, var_name)


@given(names=distinct_names_with_var_strategy())
@settings(max_examples=100)
def test_local_var_with_known_type_resolves(
    names: tuple[str, str, str, str],
) -> None:
    """
    **Feature: improved-call-resolution, Property 2: Unknown receiver produces unresolved**
    **Validates: Requirements 1.1, 2.1, 2.3**

    For any method call on a local variable declared with a known type (via short
    declaration from composite literal), the call SHALL be resolved to the correct
    method on that type.
    """
    caller_name, method_name, type_name, var_name = names

    # Build source with a type and method that ARE defined
    # Variable is declared via short declaration from composite literal
    source_code = f"""package main

type {type_name} struct {{}}

func (r *{type_name}) {method_name}() {{
}}

func {caller_name}() {{
    {var_name} := &{type_name}{{}}
    {var_name}.{method_name}()
}}
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create go.mod
        go_mod_path = Path(tmpdir) / "go.mod"
        go_mod_path.write_text("module testmodule\n")

        # Create source file
        source_path = Path(tmpdir) / "main.go"
        source_path.write_text(source_code)

        # Phase 1: Scan to build symbol table
        parser = _create_parser()
        scanner = GoScanner(parser, _id_generator)
        symbol_table = scanner.scan_directory(Path(tmpdir))

        # Phase 2: Resolve references
        resolver = GoResolver(parser, "test-project", LanguageType.GO, _id_generator)
        ir = resolver.resolve_directory(Path(tmpdir), symbol_table, "testmodule")

        # Find the caller function
        caller_qualified = f"testmodule.{caller_name}"
        caller_id = _id_generator(caller_qualified, "()")

        assert caller_id in ir.callables, f"Caller function not found in IR"
        caller = ir.callables[caller_id]

        # The method should be resolved correctly
        method_qualified = f"testmodule.{type_name}.{method_name}"
        expected_callee_id = _id_generator(method_qualified, "()")

        assert expected_callee_id in caller.calls, (
            f"Expected method {method_qualified} to be resolved for variable {var_name}. "
            f"Caller calls: {caller.calls}"
        )
