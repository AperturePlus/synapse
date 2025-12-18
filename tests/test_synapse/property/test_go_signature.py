"""Property tests for Go function signature resolution.

**Feature: go-signature-resolution**

Tests that verify signature storage and resolution for Go functions and methods.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings, strategies as st

from synapse.adapters.go.scanner import GoScanner
from synapse.adapters.go.ast_utils import GoAstUtils
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


# Strategies for generating Go parameter types
go_basic_types = st.sampled_from([
    "int", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64",
    "float32", "float64", "string", "bool", "byte", "rune",
])

go_param_names = st.from_regex(r"[a-z][a-zA-Z0-9]{0,10}", fullmatch=True)
go_func_names = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,15}", fullmatch=True)
go_type_names = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,10}", fullmatch=True)


@st.composite
def go_param_strategy(draw: st.DrawFn) -> tuple[str, str]:
    """Generate a Go parameter (name, type) pair."""
    name = draw(go_param_names)
    param_type = draw(go_basic_types)
    return (name, param_type)


@st.composite
def go_function_strategy(draw: st.DrawFn) -> tuple[str, list[tuple[str, str]]]:
    """Generate a Go function name and parameter list."""
    func_name = draw(go_func_names)
    params = draw(st.lists(go_param_strategy(), min_size=0, max_size=5))
    return (func_name, params)


@st.composite
def go_method_strategy(draw: st.DrawFn) -> tuple[str, str, list[tuple[str, str]]]:
    """Generate a Go method with receiver type, name, and parameters."""
    receiver_type = draw(go_type_names)
    method_name = draw(go_func_names)
    params = draw(st.lists(go_param_strategy(), min_size=0, max_size=5))
    return (receiver_type, method_name, params)


def _build_go_function_source(func_name: str, params: list[tuple[str, str]]) -> str:
    """Build Go source code for a function declaration."""
    param_str = ", ".join(f"{name} {ptype}" for name, ptype in params)
    return f"""package main

func {func_name}({param_str}) {{
}}
"""


def _build_go_method_source(
    receiver_type: str, method_name: str, params: list[tuple[str, str]]
) -> str:
    """Build Go source code for a method declaration."""
    param_str = ", ".join(f"{name} {ptype}" for name, ptype in params)
    return f"""package main

type {receiver_type} struct {{}}

func (r *{receiver_type}) {method_name}({param_str}) {{
}}
"""


def _expected_signature(params: list[tuple[str, str]]) -> str:
    """Build expected signature string from parameters."""
    if not params:
        return "()"
    type_list = ", ".join(ptype for _, ptype in params)
    return f"({type_list})"


@given(func_data=go_function_strategy())
@settings(max_examples=100)
def test_function_signature_storage_completeness(
    func_data: tuple[str, list[tuple[str, str]]]
) -> None:
    """
    **Feature: go-signature-resolution, Property 1: Signature Storage Completeness**
    **Validates: Requirements 3.1, 3.3**

    For any Go function declaration scanned by GoScanner, the symbol table
    SHALL contain the function's signature in callable_signatures with the
    correct format matching GoAstUtils.build_signature.
    """
    func_name, params = func_data
    source_code = _build_go_function_source(func_name, params)
    expected_sig = _expected_signature(params)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create go.mod
        go_mod_path = Path(tmpdir) / "go.mod"
        go_mod_path.write_text("module testmodule\n")

        # Create source file
        source_path = Path(tmpdir) / "main.go"
        source_path.write_text(source_code)

        # Scan with GoScanner
        parser = _create_parser()
        scanner = GoScanner(parser, _id_generator)
        symbol_table = scanner.scan_directory(Path(tmpdir))

        # Verify signature is stored
        qualified_name = f"testmodule.{func_name}"
        assert qualified_name in symbol_table.callable_map.get(func_name, []), (
            f"Function {func_name} not found in callable_map"
        )

        stored_sig = symbol_table.get_callable_signature(qualified_name)
        assert stored_sig is not None, (
            f"Signature not stored for {qualified_name}"
        )
        assert stored_sig == expected_sig, (
            f"Signature mismatch: expected {expected_sig}, got {stored_sig}"
        )


@given(method_data=go_method_strategy())
@settings(max_examples=100)
def test_method_signature_storage_completeness(
    method_data: tuple[str, str, list[tuple[str, str]]]
) -> None:
    """
    **Feature: go-signature-resolution, Property 1: Signature Storage Completeness**
    **Validates: Requirements 3.1, 3.3**

    For any Go method declaration scanned by GoScanner, the symbol table
    SHALL contain the method's signature in callable_signatures with the
    correct format matching GoAstUtils.build_signature.
    """
    receiver_type, method_name, params = method_data
    source_code = _build_go_method_source(receiver_type, method_name, params)
    expected_sig = _expected_signature(params)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create go.mod
        go_mod_path = Path(tmpdir) / "go.mod"
        go_mod_path.write_text("module testmodule\n")

        # Create source file
        source_path = Path(tmpdir) / "main.go"
        source_path.write_text(source_code)

        # Scan with GoScanner
        parser = _create_parser()
        scanner = GoScanner(parser, _id_generator)
        symbol_table = scanner.scan_directory(Path(tmpdir))

        # Verify signature is stored
        qualified_name = f"testmodule.{receiver_type}.{method_name}"
        assert qualified_name in symbol_table.callable_map.get(method_name, []), (
            f"Method {method_name} not found in callable_map"
        )

        stored_sig = symbol_table.get_callable_signature(qualified_name)
        assert stored_sig is not None, (
            f"Signature not stored for {qualified_name}"
        )
        assert stored_sig == expected_sig, (
            f"Signature mismatch: expected {expected_sig}, got {stored_sig}"
        )


from synapse.adapters.go.resolver import GoResolver


def _build_go_function_with_call_source(
    func_name: str, params: list[tuple[str, str]], caller_name: str = "Caller"
) -> str:
    """Build Go source code with a function and a caller that invokes it."""
    param_str = ", ".join(f"{name} {ptype}" for name, ptype in params)
    # Build argument list with zero values for each type
    arg_str = ", ".join(_zero_value(ptype) for _, ptype in params)
    return f"""package main

func {func_name}({param_str}) {{
}}

func {caller_name}() {{
    {func_name}({arg_str})
}}
"""


def _build_go_method_with_call_source(
    receiver_type: str,
    method_name: str,
    params: list[tuple[str, str]],
    caller_name: str = "Caller",
) -> str:
    """Build Go source code with a method and a caller that invokes it."""
    param_str = ", ".join(f"{name} {ptype}" for name, ptype in params)
    arg_str = ", ".join(_zero_value(ptype) for _, ptype in params)
    return f"""package main

type {receiver_type} struct {{}}

func (r *{receiver_type}) {method_name}({param_str}) {{
}}

func {caller_name}() {{
    obj := &{receiver_type}{{}}
    obj.{method_name}({arg_str})
}}
"""


def _zero_value(go_type: str) -> str:
    """Return a zero value literal for a Go type."""
    if go_type in ("int", "int8", "int16", "int32", "int64",
                   "uint", "uint8", "uint16", "uint32", "uint64",
                   "float32", "float64", "byte", "rune"):
        return "0"
    elif go_type == "string":
        return '""'
    elif go_type == "bool":
        return "false"
    return "nil"


@given(func_data=go_function_strategy())
@settings(max_examples=100)
def test_callee_id_signature_consistency(
    func_data: tuple[str, list[tuple[str, str]]]
) -> None:
    """
    **Feature: go-signature-resolution, Property 2: Callee ID Signature Consistency**
    **Validates: Requirements 1.1, 1.2**

    For any function call where the target function exists in the symbol table,
    the generated callee ID SHALL use the signature stored in the symbol table,
    not a hardcoded value.
    """
    func_name, params = func_data
    source_code = _build_go_function_with_call_source(func_name, params)
    expected_sig = _expected_signature(params)

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
        caller_qualified = "testmodule.Caller"
        caller_id = _id_generator(caller_qualified, "()")

        assert caller_id in ir.callables, f"Caller function not found in IR"
        caller = ir.callables[caller_id]

        # The callee ID should use the actual signature from symbol table
        callee_qualified = f"testmodule.{func_name}"
        expected_callee_id = _id_generator(callee_qualified, expected_sig)

        assert expected_callee_id in caller.calls, (
            f"Expected callee ID {expected_callee_id} not in caller.calls. "
            f"Caller calls: {caller.calls}. "
            f"Expected signature: {expected_sig}"
        )


@given(method_data=go_method_strategy())
@settings(max_examples=100)
def test_method_call_signature_resolution(
    method_data: tuple[str, str, list[tuple[str, str]]]
) -> None:
    """
    **Feature: go-signature-resolution, Property 3: Method Call Signature Resolution**
    **Validates: Requirements 1.3**

    For any method call via selector expression where the target method exists
    in the symbol table, the generated callee ID SHALL use the method's signature
    from the symbol table.
    """
    receiver_type, method_name, params = method_data
    source_code = _build_go_method_with_call_source(receiver_type, method_name, params)
    expected_sig = _expected_signature(params)

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
        caller_qualified = "testmodule.Caller"
        caller_id = _id_generator(caller_qualified, "()")

        assert caller_id in ir.callables, f"Caller function not found in IR"
        caller = ir.callables[caller_id]

        # The callee ID should use the actual signature from symbol table
        callee_qualified = f"testmodule.{receiver_type}.{method_name}"
        expected_callee_id = _id_generator(callee_qualified, expected_sig)

        assert expected_callee_id in caller.calls, (
            f"Expected callee ID {expected_callee_id} not in caller.calls. "
            f"Caller calls: {caller.calls}. "
            f"Expected signature: {expected_sig}"
        )


# Strategy for generating unknown function names (not defined in the module)
unknown_func_names = st.from_regex(r"Unknown[A-Z][a-zA-Z0-9]{0,10}", fullmatch=True)


def _build_go_caller_with_unknown_call(caller_name: str, unknown_func: str) -> str:
    """Build Go source code with a caller that invokes an unknown function."""
    return f"""package main

func {caller_name}() {{
    {unknown_func}()
}}
"""


@given(
    caller_name=go_func_names,
    unknown_func=unknown_func_names,
)
@settings(max_examples=100)
def test_unresolved_function_recording(caller_name: str, unknown_func: str) -> None:
    """
    **Feature: go-signature-resolution, Property 4: Unresolved Function Recording**
    **Validates: Requirements 2.1**

    For any function call where the target function is not found in the symbol table,
    the system SHALL record an unresolved reference with reason
    "Function not found in symbol table".
    """
    source_code = _build_go_caller_with_unknown_call(caller_name, unknown_func)

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

        # Verify unresolved reference is recorded
        unresolved_for_caller = [
            ref for ref in ir.unresolved if ref.source_callable == caller_id
        ]

        assert len(unresolved_for_caller) >= 1, (
            f"Expected at least one unresolved reference for caller {caller_id}, "
            f"but found {len(unresolved_for_caller)}"
        )

        # Find the specific unresolved reference for our unknown function
        matching_refs = [
            ref for ref in unresolved_for_caller if ref.target_name == unknown_func
        ]

        assert len(matching_refs) == 1, (
            f"Expected exactly one unresolved reference for {unknown_func}, "
            f"but found {len(matching_refs)}. All unresolved: {unresolved_for_caller}"
        )

        ref = matching_refs[0]
        assert ref.reason == "Function not found in symbol table", (
            f"Expected reason 'Function not found in symbol table', got '{ref.reason}'"
        )


@given(func_data=go_function_strategy())
@settings(max_examples=100)
def test_callee_id_roundtrip_consistency(
    func_data: tuple[str, list[tuple[str, str]]]
) -> None:
    """
    **Feature: go-signature-resolution, Property 5: Callee ID Round-Trip Consistency**
    **Validates: Requirements 1.2, 3.2**

    For any function definition and a call to that function within the same project,
    the callee ID generated during call resolution SHALL equal the callable ID
    generated during function definition.
    """
    func_name, params = func_data
    source_code = _build_go_function_with_call_source(func_name, params)

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

        # Get the function definition ID from ir.callables
        func_qualified = f"testmodule.{func_name}"
        expected_sig = _expected_signature(params)
        definition_id = _id_generator(func_qualified, expected_sig)

        assert definition_id in ir.callables, (
            f"Function definition {definition_id} not found in ir.callables. "
            f"Available callables: {list(ir.callables.keys())}"
        )

        # Get the caller and verify the callee ID matches the definition ID
        caller_qualified = "testmodule.Caller"
        caller_id = _id_generator(caller_qualified, "()")

        assert caller_id in ir.callables, f"Caller function not found in IR"
        caller = ir.callables[caller_id]

        # The callee ID in caller.calls should match the definition ID exactly
        assert definition_id in caller.calls, (
            f"Round-trip consistency failed: "
            f"Definition ID {definition_id} not found in caller.calls. "
            f"Caller calls: {caller.calls}"
        )


@given(method_data=go_method_strategy())
@settings(max_examples=100)
def test_method_callee_id_roundtrip_consistency(
    method_data: tuple[str, str, list[tuple[str, str]]]
) -> None:
    """
    **Feature: go-signature-resolution, Property 5: Callee ID Round-Trip Consistency**
    **Validates: Requirements 1.2, 3.2**

    For any method definition and a call to that method within the same project,
    the callee ID generated during call resolution SHALL equal the callable ID
    generated during method definition.
    """
    receiver_type, method_name, params = method_data
    source_code = _build_go_method_with_call_source(receiver_type, method_name, params)

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

        # Get the method definition ID from ir.callables
        method_qualified = f"testmodule.{receiver_type}.{method_name}"
        expected_sig = _expected_signature(params)
        definition_id = _id_generator(method_qualified, expected_sig)

        assert definition_id in ir.callables, (
            f"Method definition {definition_id} not found in ir.callables. "
            f"Available callables: {list(ir.callables.keys())}"
        )

        # Get the caller and verify the callee ID matches the definition ID
        caller_qualified = "testmodule.Caller"
        caller_id = _id_generator(caller_qualified, "()")

        assert caller_id in ir.callables, f"Caller function not found in IR"
        caller = ir.callables[caller_id]

        # The callee ID in caller.calls should match the definition ID exactly
        assert definition_id in caller.calls, (
            f"Round-trip consistency failed: "
            f"Definition ID {definition_id} not found in caller.calls. "
            f"Caller calls: {caller.calls}"
        )
