"""Laravel semantic enrichment for PHP IR.

Best-effort extraction of HTTP routes from `routes/*.php` and attachment to
controller methods as `Callable.routes` entries.
"""

from __future__ import annotations

import re
from pathlib import Path

from synapse.core.models import Callable as CallableEntity
from synapse.core.models import IR, LanguageType
from synapse.enrichers.base import IREnricher


_ROUTE_CALL_RE = re.compile(
    r"Route::(?P<method>get|post|put|patch|delete|options|any)\s*\(\s*"
    r"(?P<q>['\"])(?P<path>[^'\"]+)(?P=q)\s*,\s*(?P<action>[^\)]+)\)",
    re.IGNORECASE,
)
_ARRAY_ACTION_RE = re.compile(
    r"\[\s*(?P<class>[A-Za-z0-9_\\]+)::class\s*,\s*"
    r"(?P<q>['\"])(?P<method>[A-Za-z0-9_]+)(?P=q)\s*\]",
)
_STRING_ACTION_RE = re.compile(
    r"(?P<q>['\"])(?P<class>[A-Za-z0-9_\\]+)@(?P<method>[A-Za-z0-9_]+)(?P=q)"
)

_RESOURCE_RE = re.compile(
    r"Route::(?P<kind>resource|apiResource)\s*\(\s*(?P<q>['\"])"
    r"(?P<base>[^'\"]+)(?P=q)\s*,\s*(?P<class>[A-Za-z0-9_\\]+)::class",
    re.IGNORECASE,
)


class LaravelEnricher(IREnricher):
    """Enrich PHP IR with Laravel routing semantics."""

    @property
    def name(self) -> str:
        return "laravel"

    @property
    def supported_languages(self) -> set[LanguageType]:
        return {LanguageType.PHP}

    def enrich(self, ir: IR, source_path: Path) -> None:
        routes_dir = source_path / "routes"
        if not routes_dir.exists():
            return

        type_id_by_qname = {t.qualified_name: t.id for t in ir.types.values()}
        type_qnames_by_name: dict[str, list[str]] = {}
        for t in ir.types.values():
            type_qnames_by_name.setdefault(t.name, []).append(t.qualified_name)

        for route_file in sorted(routes_dir.rglob("*.php")):
            text = route_file.read_text(encoding="utf-8", errors="ignore")
            self._apply_route_calls(text, ir, type_id_by_qname, type_qnames_by_name)
            self._apply_resource_routes(text, ir, type_id_by_qname, type_qnames_by_name)

    def _apply_route_calls(
        self,
        text: str,
        ir: IR,
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
    ) -> None:
        for match in _ROUTE_CALL_RE.finditer(text):
            method = match.group("method").upper()
            path = match.group("path")
            action = match.group("action")

            controller_class, controller_method = self._parse_action(action)
            if controller_class is None or controller_method is None:
                continue

            callable_obj = self._find_controller_callable(
                ir, controller_class, controller_method, type_id_by_qname, type_qnames_by_name
            )
            if callable_obj is None:
                continue

            route = f"{method} {path}"
            if route not in callable_obj.routes:
                callable_obj.routes.append(route)
            if "laravel:route" not in callable_obj.stereotypes:
                callable_obj.stereotypes.append("laravel:route")

    def _apply_resource_routes(
        self,
        text: str,
        ir: IR,
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
    ) -> None:
        for match in _RESOURCE_RE.finditer(text):
            kind = match.group("kind").lower()
            base = match.group("base").strip("/")
            controller_class = match.group("class")
            routes = self._resource_route_matrix(kind, base)
            for method, path, action_method in routes:
                callable_obj = self._find_controller_callable(
                    ir, controller_class, action_method, type_id_by_qname, type_qnames_by_name
                )
                if callable_obj is None:
                    continue
                route = f"{method} {path}"
                if route not in callable_obj.routes:
                    callable_obj.routes.append(route)
                if "laravel:route" not in callable_obj.stereotypes:
                    callable_obj.stereotypes.append("laravel:route")

    def _resource_route_matrix(self, kind: str, base: str) -> list[tuple[str, str, str]]:
        prefix = f"/{base}"
        if kind == "apiresource":
            return [
                ("GET", prefix, "index"),
                ("POST", prefix, "store"),
                ("GET", f"{prefix}/{{id}}", "show"),
                ("PUT", f"{prefix}/{{id}}", "update"),
                ("PATCH", f"{prefix}/{{id}}", "update"),
                ("DELETE", f"{prefix}/{{id}}", "destroy"),
            ]
        # resource
        return [
            ("GET", prefix, "index"),
            ("GET", f"{prefix}/create", "create"),
            ("POST", prefix, "store"),
            ("GET", f"{prefix}/{{id}}", "show"),
            ("GET", f"{prefix}/{{id}}/edit", "edit"),
            ("PUT", f"{prefix}/{{id}}", "update"),
            ("PATCH", f"{prefix}/{{id}}", "update"),
            ("DELETE", f"{prefix}/{{id}}", "destroy"),
        ]

    def _parse_action(self, action_text: str) -> tuple[str | None, str | None]:
        array_match = _ARRAY_ACTION_RE.search(action_text)
        if array_match:
            return array_match.group("class"), array_match.group("method")

        string_match = _STRING_ACTION_RE.search(action_text)
        if string_match:
            return string_match.group("class"), string_match.group("method")

        return None, None

    def _find_controller_callable(
        self,
        ir: IR,
        controller_class: str,
        controller_method: str,
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
    ) -> CallableEntity | None:
        normalized_qname = controller_class.replace("\\\\", ".")
        type_id = type_id_by_qname.get(normalized_qname)
        if type_id is None:
            short = normalized_qname.split(".")[-1]
            candidates = type_qnames_by_name.get(short, [])
            if len(candidates) == 1:
                type_id = type_id_by_qname.get(candidates[0])
        if type_id is None:
            return None

        typ = ir.types.get(type_id)
        if typ is None:
            return None

        for call_id in typ.callables:
            c = ir.callables.get(call_id)
            if c and c.name == controller_method:
                return c
        return None
