"""Spring/Spring Boot semantic enrichment for Java IR.

Best-effort extraction of:
- Spring stereotypes (@Controller/@Service/@Repository/...)
- HTTP route mappings (@GetMapping/@PostMapping/@RequestMapping/...)
- Dependency injection points (@Autowired/@Inject/@Resource and constructor injection)
- JPA repository -> entity links (JpaRepository<Ent, ...>)
"""

from __future__ import annotations

import re
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from synapse.adapters.java.ast_utils import JavaAstUtils
from synapse.core.models import IR, LanguageType, Relationship
from synapse.enrichers.base import IREnricher


_COMPONENT_ANNOTATIONS = {
    "Component",
    "Service",
    "Repository",
    "Controller",
    "RestController",
    "Configuration",
    "SpringBootApplication",
}
_CONTROLLER_ANNOTATIONS = {"Controller", "RestController"}
_INJECTION_ANNOTATIONS = {"Autowired", "Inject", "Resource"}
_BEAN_ANNOTATIONS = {"Bean"}
_ENTITY_ANNOTATIONS = {"Entity"}

_ROUTE_ANNOTATIONS_TO_METHOD = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

_REQUEST_MAPPING = "RequestMapping"
_REQUEST_METHOD_RE = re.compile(r"RequestMethod\.([A-Z]+)")
_STRING_LITERAL_RE = re.compile(r"\"((?:\\\\\"|[^\"])*)\"")
_ANNOTATION_NAME_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_\\.]+)")
_MAPPING_VALUE_OR_PATH_RE = re.compile(
    r"\\b(?:value|path)\\s*=\\s*(\\{[^}]*\\}|\"(?:\\\\\"|[^\"])*\")"
)
_ARG_KEY_ASSIGN_RE = re.compile(r"\\b[A-Za-z_][A-Za-z0-9_]*\\s*=")

_JPA_REPOSITORY_BASES = {
    "JpaRepository",
    "CrudRepository",
    "PagingAndSortingRepository",
}
_GENERIC_FIRST_ARG_RE = re.compile(r"<\\s*([A-Za-z_][A-Za-z0-9_\\.]*)")


class SpringEnricher(IREnricher):
    """Enrich Java IR with Spring/Spring Boot semantics."""

    def __init__(self) -> None:
        self._language = Language(tsjava.language())
        self._parser = Parser(self._language)

    @property
    def name(self) -> str:
        return "spring"

    @property
    def supported_languages(self) -> set[LanguageType]:
        return {LanguageType.JAVA}

    def enrich(self, ir: IR, source_path: Path) -> None:
        type_id_by_qname = {t.qualified_name: t.id for t in ir.types.values()}
        type_qnames_by_name: dict[str, list[str]] = {}
        for t in ir.types.values():
            type_qnames_by_name.setdefault(t.name, []).append(t.qualified_name)

        callable_id_by_key = {(c.qualified_name, c.signature): c.id for c in ir.callables.values()}
        seen_relationships: set[tuple[str, str, str]] = set()

        java_files = sorted(source_path.rglob("*.java"))
        for java_file in java_files:
            content = java_file.read_bytes()
            tree = self._parser.parse(content)
            root = tree.root_node

            package_name = JavaAstUtils.extract_package(root, content)
            imports = JavaAstUtils.extract_imports(root, content)

            self._walk_types(
                node=root,
                content=content,
                package_name=package_name,
                imports=imports,
                parent_qname=None,
                ir=ir,
                type_id_by_qname=type_id_by_qname,
                type_qnames_by_name=type_qnames_by_name,
                callable_id_by_key=callable_id_by_key,
                seen_relationships=seen_relationships,
            )

    def _walk_types(
        self,
        node: Node,
        content: bytes,
        package_name: str,
        imports: list[str],
        parent_qname: str | None,
        ir: IR,
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
        callable_id_by_key: dict[tuple[str, str], str],
        seen_relationships: set[tuple[str, str, str]],
    ) -> None:
        type_declarations = {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
        }

        for child in node.children:
            if child.type in type_declarations:
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue

                type_name = JavaAstUtils.get_node_text(name_node, content)
                if parent_qname:
                    qualified_name = f"{parent_qname}.{type_name}"
                elif package_name:
                    qualified_name = f"{package_name}.{type_name}"
                else:
                    qualified_name = type_name

                type_id = type_id_by_qname.get(qualified_name)
                type_obj = ir.types.get(type_id) if type_id else None

                annotation_texts = self._extract_annotation_texts(child, content)
                raw_annotations = [self._annotation_name_from_text(t) for t in annotation_texts]
                annotations = [a for a in raw_annotations if a is not None]
                if type_obj is not None:
                    self._merge_unique(type_obj.annotations, annotations)
                    self._merge_unique(type_obj.stereotypes, self._stereotypes_for_type(annotations))

                class_prefixes = self._extract_request_mapping_prefixes(annotation_texts)

                body_node = child.child_by_field_name("body")
                if body_node and type_obj is not None:
                    self._process_members(
                        owner_type_id=type_obj.id,
                        owner_type_qname=qualified_name,
                        body_node=body_node,
                        content=content,
                        package_name=package_name,
                        imports=imports,
                        class_prefixes=class_prefixes,
                        ir=ir,
                        type_id_by_qname=type_id_by_qname,
                        type_qnames_by_name=type_qnames_by_name,
                        callable_id_by_key=callable_id_by_key,
                        seen_relationships=seen_relationships,
                    )
                    self._walk_types(
                        node=body_node,
                        content=content,
                        package_name=package_name,
                        imports=imports,
                        parent_qname=qualified_name,
                        ir=ir,
                        type_id_by_qname=type_id_by_qname,
                        type_qnames_by_name=type_qnames_by_name,
                        callable_id_by_key=callable_id_by_key,
                        seen_relationships=seen_relationships,
                    )

            elif child.type in ("class_body", "interface_body", "enum_body"):
                self._walk_types(
                    node=child,
                    content=content,
                    package_name=package_name,
                    imports=imports,
                    parent_qname=parent_qname,
                    ir=ir,
                    type_id_by_qname=type_id_by_qname,
                    type_qnames_by_name=type_qnames_by_name,
                    callable_id_by_key=callable_id_by_key,
                    seen_relationships=seen_relationships,
                )

    def _process_members(
        self,
        owner_type_id: str,
        owner_type_qname: str,
        body_node: Node,
        content: bytes,
        package_name: str,
        imports: list[str],
        class_prefixes: list[str],
        ir: IR,
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
        callable_id_by_key: dict[tuple[str, str], str],
        seen_relationships: set[tuple[str, str, str]],
    ) -> None:
        constructors = [c for c in body_node.children if c.type == "constructor_declaration"]
        single_ctor = len(constructors) == 1

        for child in body_node.children:
            if child.type == "field_declaration":
                self._process_field_injection(
                    owner_type_id,
                    child,
                    content,
                    package_name,
                    imports,
                    type_id_by_qname,
                    type_qnames_by_name,
                    ir,
                    seen_relationships,
                )
                continue

            if child.type == "constructor_declaration":
                self._process_constructor_injection(
                    owner_type_id,
                    single_ctor,
                    child,
                    content,
                    package_name,
                    imports,
                    type_id_by_qname,
                    type_qnames_by_name,
                    ir,
                    seen_relationships,
                )
                continue

            if child.type == "method_declaration":
                self._process_method_semantics(
                    owner_type_id=owner_type_id,
                    owner_type_qname=owner_type_qname,
                    method_node=child,
                    content=content,
                    package_name=package_name,
                    imports=imports,
                    class_prefixes=class_prefixes,
                    ir=ir,
                    type_id_by_qname=type_id_by_qname,
                    type_qnames_by_name=type_qnames_by_name,
                    callable_id_by_key=callable_id_by_key,
                    seen_relationships=seen_relationships,
                )
                continue

            if child.type in ("class_body", "interface_body", "enum_body"):
                self._process_members(
                    owner_type_id=owner_type_id,
                    owner_type_qname=owner_type_qname,
                    body_node=child,
                    content=content,
                    package_name=package_name,
                    imports=imports,
                    class_prefixes=class_prefixes,
                    ir=ir,
                    type_id_by_qname=type_id_by_qname,
                    type_qnames_by_name=type_qnames_by_name,
                    callable_id_by_key=callable_id_by_key,
                    seen_relationships=seen_relationships,
                )

        # Repository -> entity (JPA)
        self._process_jpa_repository(
            owner_type_id,
            body_node.parent,
            content,
            package_name,
            imports,
            type_id_by_qname,
            type_qnames_by_name,
            ir,
            seen_relationships,
        )

    def _process_field_injection(
        self,
        owner_type_id: str,
        field_node: Node,
        content: bytes,
        package_name: str,
        imports: list[str],
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
        ir: IR,
        seen_relationships: set[tuple[str, str, str]],
    ) -> None:
        annotation_texts = self._extract_annotation_texts(field_node, content)
        annotations = {self._annotation_name_from_text(t) for t in annotation_texts}
        if not annotations.intersection(_INJECTION_ANNOTATIONS):
            return

        type_node = field_node.child_by_field_name("type")
        if type_node is None:
            return

        injected_type_name = JavaAstUtils.get_type_name(type_node, content)
        injected_type_id = self._resolve_type_id(
            injected_type_name, package_name, imports, type_id_by_qname, type_qnames_by_name
        )
        if injected_type_id is None:
            return

        self._add_relationship(ir, owner_type_id, injected_type_id, "INJECTS", seen_relationships)

    def _process_constructor_injection(
        self,
        owner_type_id: str,
        single_ctor: bool,
        ctor_node: Node,
        content: bytes,
        package_name: str,
        imports: list[str],
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
        ir: IR,
        seen_relationships: set[tuple[str, str, str]],
    ) -> None:
        annotation_texts = self._extract_annotation_texts(ctor_node, content)
        annotations = {self._annotation_name_from_text(t) for t in annotation_texts}
        parameters_node = ctor_node.child_by_field_name("parameters")
        has_params = parameters_node is not None and any(
            c.type in ("formal_parameter", "spread_parameter") for c in parameters_node.children
        )

        is_injection_ctor = annotations.intersection(_INJECTION_ANNOTATIONS) or (
            single_ctor and has_params
        )
        if not is_injection_ctor or parameters_node is None:
            return

        for param in parameters_node.children:
            if param.type not in ("formal_parameter", "spread_parameter"):
                continue
            type_node = param.child_by_field_name("type")
            if type_node is None:
                continue
            dep_type_name = JavaAstUtils.get_type_name(type_node, content)
            dep_type_id = self._resolve_type_id(
                dep_type_name, package_name, imports, type_id_by_qname, type_qnames_by_name
            )
            if dep_type_id is None:
                continue
            self._add_relationship(ir, owner_type_id, dep_type_id, "INJECTS", seen_relationships)

    def _process_method_semantics(
        self,
        owner_type_id: str,
        owner_type_qname: str,
        method_node: Node,
        content: bytes,
        package_name: str,
        imports: list[str],
        class_prefixes: list[str],
        ir: IR,
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
        callable_id_by_key: dict[tuple[str, str], str],
        seen_relationships: set[tuple[str, str, str]],
    ) -> None:
        name_node = method_node.child_by_field_name("name")
        if name_node is None:
            return

        method_name = JavaAstUtils.get_node_text(name_node, content)
        signature = JavaAstUtils.build_signature(method_node, content)
        qualified_name = f"{owner_type_qname}.{method_name}"
        callable_id = callable_id_by_key.get((qualified_name, signature))
        callable_obj = ir.callables.get(callable_id) if callable_id else None

        annotation_texts = self._extract_annotation_texts(method_node, content)
        raw_annotations = [self._annotation_name_from_text(t) for t in annotation_texts]
        annotations = [a for a in raw_annotations if a is not None]
        if callable_obj is not None:
            self._merge_unique(callable_obj.annotations, annotations)

        routes = self._extract_routes_from_texts(annotation_texts)
        if routes and callable_obj is not None:
            expanded = self._expand_routes_with_prefixes(class_prefixes, routes)
            self._merge_unique(callable_obj.routes, expanded)
            self._merge_unique(callable_obj.stereotypes, ["spring:route"])

        # @Bean factory methods: parameters are injected dependencies
        if set(annotations).intersection(_BEAN_ANNOTATIONS):
            params_node = method_node.child_by_field_name("parameters")
            if params_node:
                for param in params_node.children:
                    if param.type not in ("formal_parameter", "spread_parameter"):
                        continue
                    type_node = param.child_by_field_name("type")
                    if type_node is None:
                        continue
                    dep_type_name = JavaAstUtils.get_type_name(type_node, content)
                    dep_type_id = self._resolve_type_id(
                        dep_type_name,
                        package_name,
                        imports,
                        type_id_by_qname,
                        type_qnames_by_name,
                    )
                    if dep_type_id is None:
                        continue
                    self._add_relationship(
                        ir, owner_type_id, dep_type_id, "INJECTS", seen_relationships
                    )

    def _process_jpa_repository(
        self,
        owner_type_id: str,
        type_decl_node: Node | None,
        content: bytes,
        package_name: str,
        imports: list[str],
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
        ir: IR,
        seen_relationships: set[tuple[str, str, str]],
    ) -> None:
        if type_decl_node is None:
            return

        if type_decl_node.type not in ("class_declaration", "interface_declaration"):
            return

        extends_node = type_decl_node.child_by_field_name("interfaces")
        if extends_node is None:
            # interface_declaration uses "extends_interfaces" in tree-sitter-java; fall back to scan
            for child in type_decl_node.children:
                if child.type in ("extends_interfaces", "super_interfaces"):
                    extends_node = child
                    break
        if extends_node is None:
            return

        for type_ref in extends_node.children:
            text = JavaAstUtils.get_node_text(type_ref, content)
            base_type = JavaAstUtils.get_type_name(type_ref, content)
            if base_type not in _JPA_REPOSITORY_BASES:
                continue

            generic_match = _GENERIC_FIRST_ARG_RE.search(text)
            if not generic_match:
                continue

            entity_type_name = generic_match.group(1)
            entity_type_id = self._resolve_type_id(
                entity_type_name, package_name, imports, type_id_by_qname, type_qnames_by_name
            )
            if entity_type_id is None:
                continue

            self._add_relationship(ir, owner_type_id, entity_type_id, "PERSISTS", seen_relationships)

    def _extract_annotation_texts(self, node: Node, content: bytes) -> list[str]:
        texts: list[str] = []
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if "annotation" in mod.type:
                        texts.append(JavaAstUtils.get_node_text(mod, content).strip())
            elif "annotation" in child.type:
                texts.append(JavaAstUtils.get_node_text(child, content).strip())
        return texts

    def _annotation_name_from_text(self, annotation_text: str) -> str | None:
        match = _ANNOTATION_NAME_RE.search(annotation_text)
        if not match:
            return None
        return match.group(1).split(".")[-1]

    def _stereotypes_for_type(self, annotations: list[str]) -> list[str]:
        stereotypes: list[str] = []
        for ann in annotations:
            if ann in _CONTROLLER_ANNOTATIONS:
                stereotypes.append("spring:controller")
            if ann in _COMPONENT_ANNOTATIONS:
                stereotypes.append("spring:component")
            if ann in _ENTITY_ANNOTATIONS:
                stereotypes.append("jpa:entity")
        return stereotypes

    def _extract_request_mapping_prefixes(self, annotation_texts: list[str]) -> list[str]:
        prefixes: list[str] = []
        for text in annotation_texts:
            name = self._annotation_name_from_text(text)
            if name != _REQUEST_MAPPING:
                continue
            for path in self._extract_mapping_paths(text):
                prefixes.append(self._normalize_path(path))
        return prefixes or [""]

    def _extract_routes_from_texts(self, annotation_texts: list[str]) -> list[str]:
        routes: list[str] = []
        for text in annotation_texts:
            name = self._annotation_name_from_text(text)
            if not name:
                continue

            if name in _ROUTE_ANNOTATIONS_TO_METHOD:
                method = _ROUTE_ANNOTATIONS_TO_METHOD[name]
                paths = self._extract_mapping_paths(text) or ["/"]
                for path in paths:
                    routes.append(f"{method} {self._normalize_path(path)}")
                continue

            if name == _REQUEST_MAPPING:
                methods = _REQUEST_METHOD_RE.findall(text)
                if not methods:
                    methods = ["ANY"]
                paths = self._extract_mapping_paths(text) or ["/"]
                for m in methods:
                    for path in paths:
                        routes.append(f"{m} {self._normalize_path(path)}")

        return routes

    def _extract_mapping_paths(self, annotation_text: str) -> list[str]:
        # Prefer explicit `value=` / `path=` assignments.
        assigned: list[str] = []
        for match in _MAPPING_VALUE_OR_PATH_RE.finditer(annotation_text):
            assigned.extend([m.group(1) for m in _STRING_LITERAL_RE.finditer(match.group(1))])
        if assigned:
            return assigned

        # Otherwise, treat leading positional argument(s) as path and ignore named attributes.
        start = annotation_text.find("(")
        end = annotation_text.rfind(")")
        if start == -1 or end == -1 or end <= start:
            return []
        args = annotation_text[start + 1 : end]
        key_match = _ARG_KEY_ASSIGN_RE.search(args)
        if key_match:
            args = args[: key_match.start()]

        return [m.group(1) for m in _STRING_LITERAL_RE.finditer(args)]

    def _normalize_path(self, path: str) -> str:
        p = path.strip()
        if not p:
            return "/"
        return p if p.startswith("/") else f"/{p}"

    def _expand_routes_with_prefixes(self, prefixes: list[str], routes: list[str]) -> list[str]:
        expanded: list[str] = []
        for route in routes:
            if " " not in route:
                expanded.append(route)
                continue
            method, path = route.split(" ", 1)
            for prefix in prefixes:
                combined = self._join_paths(prefix, path)
                expanded.append(f"{method} {combined}")
        return expanded

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

    def _resolve_type_id(
        self,
        type_name: str,
        package_name: str,
        imports: list[str],
        type_id_by_qname: dict[str, str],
        type_qnames_by_name: dict[str, list[str]],
    ) -> str | None:
        if "." in type_name and type_name in type_id_by_qname:
            return type_id_by_qname[type_name]

        if package_name:
            same_pkg = f"{package_name}.{type_name}"
            if same_pkg in type_id_by_qname:
                return type_id_by_qname[same_pkg]

        for imp in imports:
            if imp.endswith(f".{type_name}") and imp in type_id_by_qname:
                return type_id_by_qname[imp]

        for imp in imports:
            if imp.endswith(".*"):
                candidate = f"{imp[:-2]}.{type_name}"
                if candidate in type_id_by_qname:
                    return type_id_by_qname[candidate]

        candidates = type_qnames_by_name.get(type_name, [])
        if len(candidates) == 1 and candidates[0] in type_id_by_qname:
            return type_id_by_qname[candidates[0]]

        return None

    def _merge_unique(self, target: list[str], values: list[str]) -> None:
        existing = set(target)
        for v in values:
            if v not in existing:
                target.append(v)
                existing.add(v)

    def _add_relationship(
        self,
        ir: IR,
        source_id: str,
        target_id: str,
        relationship_type: str,
        seen: set[tuple[str, str, str]],
    ) -> None:
        key = (source_id, relationship_type, target_id)
        if key in seen:
            return
        seen.add(key)
        ir.relationships.append(
            Relationship(
                source_id=source_id,
                target_id=target_id,
                relationship_type=relationship_type,
            )
        )
