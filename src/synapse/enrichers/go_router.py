"""Shared Go HTTP router enrichment helpers.

These helpers implement best-effort extraction of HTTP routes from common Go
router frameworks by scanning Go source files with tree-sitter-go. The extracted
routes are attached to existing IR callables as `Callable.routes` entries.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_go as tsgo
from tree_sitter import Language, Node, Parser

from synapse.adapters.go.ast_utils import GoAstUtils
from synapse.core.models import Callable as CallableEntity
from synapse.core.models import IR, LanguageType


_GO_STRING_LITERAL_TYPES = {"interpreted_string_literal", "raw_string_literal"}
_GO_DEFAULT_ALIAS_VERSION_RE = re.compile(r"^v\\d+$")


@dataclass(frozen=True)
class GoRouterConfig:
    """Configuration for extracting routes from a Go router framework."""

    framework: str
    import_prefixes: tuple[str, ...]
    path_first_methods: dict[str, str]
    verb_path_methods: frozenset[str] = frozenset()
    group_method: str = "Group"

    @property
    def route_stereotype(self) -> str:
        return f"{self.framework}:route"


class GoRouterRouteExtractor:
    """Extract and attach routes for a specific Go router framework."""

    def __init__(self, config: GoRouterConfig) -> None:
        self._config = config
        self._language = Language(tsgo.language())
        self._parser = Parser(self._language)

    def enrich(self, ir: IR, source_path: Path) -> None:
        module_name = self._read_module_name(source_path)

        callables_by_qname: dict[str, CallableEntity] = {
            c.qualified_name: c
            for c in ir.callables.values()
            if c.language_type == LanguageType.GO
        }

        go_files = sorted(source_path.rglob("*.go"))
        for go_file in go_files:
            if go_file.name.endswith("_test.go"):
                continue
            if "vendor" in go_file.parts:
                continue

            content = go_file.read_bytes()
            tree = self._parser.parse(content)
            root = tree.root_node

            package_name = GoAstUtils.extract_package(root, content)
            if not package_name:
                continue

            qualified_pkg = self._qualified_package(
                source_path=source_path,
                file_path=go_file,
                module_name=module_name,
                package_name=package_name,
            )

            import_aliases, import_paths = self._extract_imports(root, content)
            if not self._mentions_framework(import_paths):
                continue

            group_prefix_by_var: dict[str, str] = {}
            self._walk(
                node=root,
                content=content,
                qualified_pkg=qualified_pkg,
                import_aliases=import_aliases,
                group_prefix_by_var=group_prefix_by_var,
                callables_by_qname=callables_by_qname,
            )

    def _walk(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        import_aliases: dict[str, str],
        group_prefix_by_var: dict[str, str],
        callables_by_qname: dict[str, CallableEntity],
    ) -> None:
        if node.type in ("short_var_declaration", "assignment_statement"):
            self._maybe_capture_group_assignment(
                node=node,
                content=content,
                group_prefix_by_var=group_prefix_by_var,
            )
        elif node.type == "call_expression":
            self._maybe_capture_route_call(
                call_node=node,
                content=content,
                qualified_pkg=qualified_pkg,
                import_aliases=import_aliases,
                group_prefix_by_var=group_prefix_by_var,
                callables_by_qname=callables_by_qname,
            )

        for child in node.children:
            self._walk(
                node=child,
                content=content,
                qualified_pkg=qualified_pkg,
                import_aliases=import_aliases,
                group_prefix_by_var=group_prefix_by_var,
                callables_by_qname=callables_by_qname,
            )

    def _maybe_capture_group_assignment(
        self,
        node: Node,
        content: bytes,
        group_prefix_by_var: dict[str, str],
    ) -> None:
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")
        if left_node is None or right_node is None:
            return

        left_ident = self._single_identifier_from_expression_list(left_node, content)
        if left_ident is None:
            return

        call_expr = self._single_call_from_expression_list(right_node)
        if call_expr is None:
            return

        group_prefix = self._extract_group_prefix_from_call(
            call_node=call_expr,
            content=content,
            group_prefix_by_var=group_prefix_by_var,
        )
        if group_prefix is None:
            return

        group_prefix_by_var[left_ident] = group_prefix

    def _maybe_capture_route_call(
        self,
        call_node: Node,
        content: bytes,
        qualified_pkg: str,
        import_aliases: dict[str, str],
        group_prefix_by_var: dict[str, str],
        callables_by_qname: dict[str, CallableEntity],
    ) -> None:
        method_info = self._route_method_info(call_node, content)
        if method_info is None:
            return

        receiver_node, field_name = method_info
        args = self._call_arguments(call_node)
        if not args:
            return

        http_method: str | None = None
        path: str | None = None
        handler_node: Node | None = None

        if field_name in self._config.path_first_methods:
            if len(args) < 2:
                return
            http_method = self._config.path_first_methods[field_name]
            path = self._string_literal_value(args[0], content)
            handler_node = args[-1]
        elif field_name in self._config.verb_path_methods:
            if len(args) < 3:
                return
            verb = self._string_literal_value(args[0], content)
            http_method = verb.upper() if verb else None
            path = self._string_literal_value(args[1], content)
            handler_node = args[-1]

        if http_method is None or path is None or handler_node is None:
            return

        receiver_prefix = self._resolve_receiver_prefix(
            receiver_node=receiver_node,
            content=content,
            group_prefix_by_var=group_prefix_by_var,
        )
        full_path = self._join_paths(receiver_prefix, self._normalize_path(path))

        callable_qname = self._resolve_handler_qname(
            handler_node=handler_node,
            content=content,
            qualified_pkg=qualified_pkg,
            import_aliases=import_aliases,
        )
        if callable_qname is None:
            return

        callable_obj = callables_by_qname.get(callable_qname)
        if callable_obj is None:
            return

        route = f"{http_method} {full_path}"
        if route not in callable_obj.routes:
            callable_obj.routes.append(route)
        if self._config.route_stereotype not in callable_obj.stereotypes:
            callable_obj.stereotypes.append(self._config.route_stereotype)

    def _mentions_framework(self, import_paths: set[str]) -> bool:
        for path in import_paths:
            if any(path == prefix or path.startswith(prefix + "/") for prefix in self._config.import_prefixes):
                return True
        return False

    def _route_method_info(self, call_node: Node, content: bytes) -> tuple[Node, str] | None:
        func_node = call_node.child_by_field_name("function")
        if func_node is None or func_node.type != "selector_expression":
            return None

        field_node = func_node.child_by_field_name("field")
        operand_node = func_node.child_by_field_name("operand")
        if field_node is None or operand_node is None:
            return None

        field_name = GoAstUtils.get_node_text(field_node, content)
        if field_name in self._config.path_first_methods or field_name in self._config.verb_path_methods:
            return operand_node, field_name
        return None

    def _resolve_receiver_prefix(
        self,
        receiver_node: Node,
        content: bytes,
        group_prefix_by_var: dict[str, str],
    ) -> str:
        if receiver_node.type == "identifier":
            name = GoAstUtils.get_node_text(receiver_node, content)
            return group_prefix_by_var.get(name, "")

        if receiver_node.type == "call_expression":
            group_prefix = self._extract_group_prefix_from_call(
                call_node=receiver_node,
                content=content,
                group_prefix_by_var=group_prefix_by_var,
            )
            return group_prefix or ""

        return ""

    def _extract_group_prefix_from_call(
        self,
        call_node: Node,
        content: bytes,
        group_prefix_by_var: dict[str, str],
    ) -> str | None:
        func_node = call_node.child_by_field_name("function")
        if func_node is None or func_node.type != "selector_expression":
            return None

        field_node = func_node.child_by_field_name("field")
        operand_node = func_node.child_by_field_name("operand")
        if field_node is None or operand_node is None:
            return None

        field_name = GoAstUtils.get_node_text(field_node, content)
        if field_name != self._config.group_method:
            return None

        args = self._call_arguments(call_node)
        if not args:
            return None

        segment = self._string_literal_value(args[0], content)
        if segment is None:
            return None

        parent_prefix = self._resolve_receiver_prefix(
            receiver_node=operand_node,
            content=content,
            group_prefix_by_var=group_prefix_by_var,
        )
        return self._join_paths(parent_prefix, self._normalize_path(segment))

    def _resolve_handler_qname(
        self,
        handler_node: Node,
        content: bytes,
        qualified_pkg: str,
        import_aliases: dict[str, str],
    ) -> str | None:
        if handler_node.type == "identifier":
            name = GoAstUtils.get_node_text(handler_node, content)
            return f"{qualified_pkg}.{name}"

        if handler_node.type == "selector_expression":
            operand_node = handler_node.child_by_field_name("operand")
            field_node = handler_node.child_by_field_name("field")
            if operand_node is None or field_node is None:
                return None
            if operand_node.type != "identifier":
                return None

            pkg_alias = GoAstUtils.get_node_text(operand_node, content)
            import_path = import_aliases.get(pkg_alias)
            if import_path is None:
                return None

            name = GoAstUtils.get_node_text(field_node, content)
            return f"{import_path}.{name}"

        return None

    def _extract_imports(self, root: Node, content: bytes) -> tuple[dict[str, str], set[str]]:
        aliases: dict[str, str] = {}
        paths: set[str] = set()

        for child in root.children:
            if child.type != "import_declaration":
                continue
            for spec in child.children:
                if spec.type == "import_spec":
                    self._process_import_spec(spec, content, aliases, paths)
                elif spec.type == "import_spec_list":
                    for inner in spec.children:
                        if inner.type == "import_spec":
                            self._process_import_spec(inner, content, aliases, paths)

        return aliases, paths

    def _process_import_spec(
        self,
        node: Node,
        content: bytes,
        aliases: dict[str, str],
        paths: set[str],
    ) -> None:
        path_node = node.child_by_field_name("path")
        if path_node is None or path_node.type not in _GO_STRING_LITERAL_TYPES:
            return

        import_path = self._string_literal_value(path_node, content)
        if not import_path:
            return

        paths.add(import_path)

        name_node = node.child_by_field_name("name")
        if name_node is not None:
            alias = GoAstUtils.get_node_text(name_node, content)
            if alias in {".", "_"}:
                return
            aliases[alias] = import_path
            return

        default_alias = self._default_import_alias(import_path)
        if default_alias:
            aliases[default_alias] = import_path

    def _default_import_alias(self, import_path: str) -> str:
        parts = [p for p in import_path.split("/") if p]
        if not parts:
            return ""
        last = parts[-1]
        if _GO_DEFAULT_ALIAS_VERSION_RE.fullmatch(last) and len(parts) >= 2:
            return parts[-2]
        return last

    def _call_arguments(self, call_node: Node) -> list[Node]:
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return []
        args: list[Node] = []
        for child in args_node.children:
            if child.type in ("(", ")", ","):
                continue
            args.append(child)
        return args

    def _string_literal_value(self, node: Node, content: bytes) -> str | None:
        if node.type not in _GO_STRING_LITERAL_TYPES:
            return None

        raw = GoAstUtils.get_node_text(node, content)
        if raw.startswith("`") and raw.endswith("`") and len(raw) >= 2:
            return raw[1:-1]
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            try:
                value = ast.literal_eval(raw)
            except Exception:
                return raw[1:-1]
            return value if isinstance(value, str) else None
        return None

    def _single_identifier_from_expression_list(self, expr_list: Node, content: bytes) -> str | None:
        if expr_list.type != "expression_list":
            return None
        idents = [
            GoAstUtils.get_node_text(child, content)
            for child in expr_list.children
            if child.type == "identifier"
        ]
        if len(idents) != 1:
            return None
        return idents[0]

    def _single_call_from_expression_list(self, expr_list: Node) -> Node | None:
        if expr_list.type != "expression_list":
            return None
        calls = [child for child in expr_list.children if child.type == "call_expression"]
        if len(calls) != 1:
            return None
        return calls[0]

    def _normalize_path(self, path: str) -> str:
        p = path.strip()
        if not p:
            return "/"
        return p if p.startswith("/") else f"/{p}"

    def _join_paths(self, prefix: str, path: str) -> str:
        p1 = prefix.rstrip("/")
        p2 = path.lstrip("/")
        if not p1:
            return "/" + p2 if p2 else "/"
        if not p2:
            return p1 if p1.startswith("/") else "/" + p1
        if not p1.startswith("/"):
            p1 = "/" + p1
        return f"{p1}/{p2}"

    def _qualified_package(
        self,
        source_path: Path,
        file_path: Path,
        module_name: str,
        package_name: str,
    ) -> str:
        rel_path = file_path.relative_to(source_path).parent
        rel_path_str = str(rel_path).replace("\\", "/")
        if module_name:
            if rel_path_str in ("", "."):
                return module_name
            return f"{module_name}/{rel_path_str}"
        return rel_path_str or package_name

    def _read_module_name(self, source_path: Path) -> str:
        go_mod = source_path / "go.mod"
        if not go_mod.exists():
            return ""
        try:
            content = go_mod.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("module "):
                return line[7:].strip()
        return ""

