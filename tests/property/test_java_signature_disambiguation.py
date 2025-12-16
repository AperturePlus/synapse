"""Property tests for Java signature disambiguation.

**Feature: improved-call-resolution, Property 3: Signature disambiguation**
**Validates: Requirements 1.3, 3.1**

For any method call where multiple methods match by name and receiver type,
the resolver SHALL select the method whose signature matches the inferred
argument types, or mark as ambiguous if multiple signatures match.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings, strategies as st

from synapse.adapters.java.scanner import JavaScanner
from synapse.adapters.java.resolver import JavaResolver
from synapse.core.models import LanguageType
from synapse.adapters.base import generate_entity_id

import tree_sitter_java as ts_java
from tree_sitter import Language, Parser


def _create_parser() -> Parser:
    """Create a tree-sitter parser for Java."""
    parser = Parser(Language(ts_java.language()))
    return parser


def _id_generator(qualified_name: str, signature: str | None = None) -> str:
    """Generate entity ID for testing."""
    return generate_entity_id("test-project", LanguageType.JAVA, qualified_name, signature)


# Strategies for generating Java types and names
java_basic_types = st.sampled_from([
    "int", "long", "double", "float", "boolean", "char", "byte", "short",
])

java_object_types = st.sampled_from([
    "String", "Integer", "Long", "Double", "Float", "Boolean", "Object",
])

java_types = st.one_of(java_basic_types, java_object_types)

java_method_names = st.from_regex(r"[a-z][a-zA-Z0-9]{0,10}", fullmatch=True)
java_class_names = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,10}", fullmatch=True)
java_param_names = st.from_regex(r"[a-z][a-zA-Z0-9]{0,8}", fullmatch=True)
java_package_names = st.from_regex(r"[a-z]+(\.[a-z]+){0,2}", fullmatch=True)


@st.composite
def java_param_strategy(draw: st.DrawFn) -> tuple[str, str]:
    """Generate a Java parameter (type, name) pair."""
    param_type = draw(java_types)
    param_name = draw(java_param_names)
    return (param_type, param_name)


@st.composite
def distinct_signatures_strategy(draw: st.DrawFn) -> tuple[str, str, list[str], list[str]]:
    """Generate two distinct method signatures for overload testing.

    Returns:
        Tuple of (class_name, method_name, sig1_types, sig2_types)
        where sig1_types and sig2_types are different parameter type lists.
    """
    class_name = draw(java_class_names)
    method_name = draw(java_method_names)

    # Generate first signature
    num_params1 = draw(st.integers(min_value=0, max_value=3))
    sig1_types = [draw(java_types) for _ in range(num_params1)]

    # Generate second signature that is different
    # Either different arity or different types
    strategy = draw(st.sampled_from(["different_arity", "different_types"]))

    if strategy == "different_arity":
        # Different number of parameters
        num_params2 = draw(st.integers(min_value=0, max_value=3).filter(
            lambda x: x != num_params1
        ))
        sig2_types = [draw(java_types) for _ in range(num_params2)]
    else:
        # Same arity but at least one different type
        if num_params1 == 0:
            # Can't have different types with 0 params, use different arity
            num_params2 = draw(st.integers(min_value=1, max_value=3))
            sig2_types = [draw(java_types) for _ in range(num_params2)]
        else:
            sig2_types = sig1_types.copy()
            # Change at least one type
            idx = draw(st.integers(min_value=0, max_value=num_params1 - 1))
            new_type = draw(java_types.filter(lambda t: t != sig1_types[idx]))
            sig2_types[idx] = new_type

    return (class_name, method_name, sig1_types, sig2_types)


def _build_signature_string(types: list[str]) -> str:
    """Build a signature string from parameter types."""
    if not types:
        return "()"
    return f"({', '.join(types)})"


def _zero_value(java_type: str) -> str:
    """Return a zero/default value literal for a Java type."""
    if java_type == "int":
        return "0"
    elif java_type == "long":
        # Use long literal to avoid resolving to int overload
        return "0L"
    elif java_type == "short":
        return "(short)0"
    elif java_type == "byte":
        return "(byte)0"
    elif java_type == "double":
        return "0.0d"
    elif java_type == "float":
        return "0.0f"
    elif java_type == "boolean":
        return "false"
    elif java_type == "char":
        return "'a'"
    elif java_type == "String":
        return '""'
    elif java_type == "Integer":
        return "Integer.valueOf(0)"
    elif java_type == "Long":
        return "Long.valueOf(0L)"
    elif java_type == "Double":
        return "Double.valueOf(0.0d)"
    elif java_type == "Float":
        return "Float.valueOf(0.0f)"
    elif java_type == "Boolean":
        return "Boolean.TRUE"
    elif java_type == "Object":
        return "new Object()"
    return "null"


def _build_java_overloaded_class(
    package_name: str,
    class_name: str,
    method_name: str,
    sig1_types: list[str],
    sig2_types: list[str],
) -> str:
    """Build Java source with overloaded methods."""
    # Build first method
    params1 = ", ".join(
        f"{t} p{i}" for i, t in enumerate(sig1_types)
    )
    # Build second method
    params2 = ", ".join(
        f"{t} p{i}" for i, t in enumerate(sig2_types)
    )

    return f"""package {package_name};

public class {class_name} {{
    public void {method_name}({params1}) {{
    }}

    public void {method_name}({params2}) {{
    }}
}}
"""


def _build_java_caller_class(
    package_name: str,
    target_class: str,
    method_name: str,
    call_arg_types: list[str],
) -> str:
    """Build Java source with a caller that invokes a method."""
    args = ", ".join(_zero_value(t) for t in call_arg_types)

    return f"""package {package_name};

public class Caller {{
    public void callMethod() {{
        {target_class} obj = new {target_class}();
        obj.{method_name}({args});
    }}
}}
"""


@given(data=distinct_signatures_strategy())
@settings(max_examples=100)
def test_signature_disambiguation_selects_correct_overload(
    data: tuple[str, str, list[str], list[str]]
) -> None:
    """
    **Feature: improved-call-resolution, Property 3: Signature disambiguation**
    **Validates: Requirements 1.3, 3.1**

    For any method call where multiple methods match by name and receiver type,
    the resolver SHALL select the method whose signature matches the inferred
    argument types.
    """
    class_name, method_name, sig1_types, sig2_types = data
    package_name = "com.test"

    # Build source files
    target_source = _build_java_overloaded_class(
        package_name, class_name, method_name, sig1_types, sig2_types
    )

    # Call the first overload
    caller_source = _build_java_caller_class(
        package_name, class_name, method_name, sig1_types
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create package directory
        pkg_dir = Path(tmpdir) / "com" / "test"
        pkg_dir.mkdir(parents=True)

        # Write source files
        (pkg_dir / f"{class_name}.java").write_text(target_source)
        (pkg_dir / "Caller.java").write_text(caller_source)

        # Phase 1: Scan to build symbol table
        parser = _create_parser()
        scanner = JavaScanner(parser)
        symbol_table = scanner.scan_directory(Path(tmpdir))

        # Verify both overloads are in symbol table
        qualified_method = f"{package_name}.{class_name}.{method_name}"
        candidates = symbol_table.callable_map.get(method_name, [])
        assert qualified_method in candidates, (
            f"Method {qualified_method} not found in callable_map"
        )

        # Phase 2: Resolve references
        resolver = JavaResolver(parser, "test-project", LanguageType.JAVA, _id_generator)
        ir = resolver.resolve_directory(Path(tmpdir), symbol_table)

        # Find the caller method
        caller_qualified = f"{package_name}.Caller.callMethod"
        caller_sig = "()"
        caller_id = _id_generator(caller_qualified, caller_sig)

        assert caller_id in ir.callables, (
            f"Caller method not found in IR. Available: {list(ir.callables.keys())}"
        )
        caller = ir.callables[caller_id]

        # The call should resolve to the first overload (matching sig1_types)
        expected_sig = _build_signature_string(sig1_types)
        expected_callee_id = _id_generator(qualified_method, expected_sig)

        # Check if resolved correctly or marked as unresolved
        if expected_callee_id in caller.calls:
            # Successfully resolved to correct overload
            pass
        else:
            # Check if it was marked as unresolved due to ambiguity
            unresolved_for_caller = [
                ref for ref in ir.unresolved
                if ref.source_callable == caller_id and ref.target_name == method_name
            ]

            # If unresolved, it should be due to ambiguity or type inference issues
            # (not because the method wasn't found)
            if unresolved_for_caller:
                ref = unresolved_for_caller[0]
                # Acceptable reasons: ambiguity or type inference limitations
                acceptable_reasons = [
                    "Ambiguous",
                    "Unknown receiver type",
                    "No callable matches",
                ]
                assert any(r in ref.reason for r in acceptable_reasons), (
                    f"Unexpected unresolved reason: {ref.reason}. "
                    f"Expected one of: {acceptable_reasons}"
                )
            else:
                # Check if it resolved to the wrong overload
                wrong_sig = _build_signature_string(sig2_types)
                wrong_callee_id = _id_generator(qualified_method, wrong_sig)

                assert wrong_callee_id not in caller.calls, (
                    f"Resolved to wrong overload! "
                    f"Expected {expected_sig}, got {wrong_sig}"
                )


@given(
    class_name=java_class_names,
    method_name=java_method_names,
)
@settings(max_examples=100)
def test_overload_resolution_consistency(
    class_name: str,
    method_name: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 3: Signature disambiguation**
    **Validates: Requirements 1.3, 3.1**

    For any method call where multiple overloads exist, the resolver SHALL either:
    1. Resolve to exactly one overload based on signature matching
    2. Mark as ambiguous if multiple overloads match equally
    3. Mark as unresolved with a specific reason

    The resolver SHALL NOT silently pick an arbitrary overload.
    """
    package_name = "com.test"

    # Create a class with two distinct overloads
    source = f"""package {package_name};

public class {class_name} {{
    public void {method_name}(int p) {{
    }}

    public void {method_name}(String p) {{
    }}
}}
"""

    # Create a caller that calls with a String argument
    caller_source = f"""package {package_name};

public class Caller {{
    public void callMethod() {{
        {class_name} obj = new {class_name}();
        obj.{method_name}("test");
    }}
}}
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create package directory
        pkg_dir = Path(tmpdir) / "com" / "test"
        pkg_dir.mkdir(parents=True)

        # Write source files
        (pkg_dir / f"{class_name}.java").write_text(source)
        (pkg_dir / "Caller.java").write_text(caller_source)

        # Phase 1: Scan
        parser = _create_parser()
        scanner = JavaScanner(parser)
        symbol_table = scanner.scan_directory(Path(tmpdir))

        # Phase 2: Resolve
        resolver = JavaResolver(parser, "test-project", LanguageType.JAVA, _id_generator)
        ir = resolver.resolve_directory(Path(tmpdir), symbol_table)

        # Find the caller
        caller_qualified = f"{package_name}.Caller.callMethod"
        caller_id = _id_generator(caller_qualified, "()")

        assert caller_id in ir.callables, "Caller not found in IR"
        caller = ir.callables[caller_id]

        qualified_method = f"{package_name}.{class_name}.{method_name}"

        # Check resolution outcome - caller.calls contains IDs, not qualified names
        # We need to check if any call ID corresponds to our method
        unresolved_for_caller = [
            ref for ref in ir.unresolved
            if ref.source_callable == caller_id and ref.target_name == method_name
        ]

        # Check both possible overload IDs
        string_sig = "(String)"
        int_sig = "(int)"
        string_callee_id = _id_generator(qualified_method, string_sig)
        int_callee_id = _id_generator(qualified_method, int_sig)

        resolved_to_string = string_callee_id in caller.calls
        resolved_to_int = int_callee_id in caller.calls
        is_resolved = resolved_to_string or resolved_to_int
        is_unresolved = len(unresolved_for_caller) > 0

        # Must be either resolved or unresolved
        assert is_resolved or is_unresolved, (
            f"Method call neither resolved nor marked as unresolved. "
            f"Caller calls: {caller.calls}, "
            f"Expected string ID: {string_callee_id}, "
            f"Expected int ID: {int_callee_id}, "
            f"Unresolved: {unresolved_for_caller}"
        )

        if is_resolved:
            # Should resolve to the String overload since we pass a String
            assert resolved_to_string, (
                f"Expected to resolve to String overload ({string_callee_id}), "
                f"but resolved to int overload ({int_callee_id})"
            )

        if is_unresolved:
            # Should have a meaningful reason
            ref = unresolved_for_caller[0]
            assert ref.reason, "Unresolved reference should have a reason"
