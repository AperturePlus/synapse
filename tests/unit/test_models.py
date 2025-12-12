"""Unit tests for IR data models."""

import pytest
from pydantic import ValidationError

from synapse.core.models import (
    Callable,
    CallableKind,
    IR,
    LanguageType,
    Module,
    SymbolTable,
    Type,
    TypeKind,
    UnresolvedReference,
    Visibility,
)


class TestEnums:
    """Tests for enum values."""

    def test_language_type_values(self) -> None:
        assert LanguageType.JAVA.value == "java"
        assert LanguageType.GO.value == "go"

    def test_type_kind_values(self) -> None:
        assert TypeKind.CLASS.value == "CLASS"
        assert TypeKind.INTERFACE.value == "INTERFACE"
        assert TypeKind.STRUCT.value == "STRUCT"
        assert TypeKind.ENUM.value == "ENUM"

    def test_callable_kind_values(self) -> None:
        assert CallableKind.FUNCTION.value == "FUNCTION"
        assert CallableKind.METHOD.value == "METHOD"
        assert CallableKind.CONSTRUCTOR.value == "CONSTRUCTOR"

    def test_visibility_values(self) -> None:
        assert Visibility.PUBLIC.value == "public"
        assert Visibility.PRIVATE.value == "private"
        assert Visibility.PROTECTED.value == "protected"
        assert Visibility.PACKAGE.value == "package"


class TestModule:
    """Tests for Module model."""

    def test_create_module(self) -> None:
        module = Module(
            id="mod1",
            name="models",
            qualified_name="com.example.models",
            path="/src/com/example/models",
            language_type=LanguageType.JAVA,
        )
        assert module.id == "mod1"
        assert module.name == "models"
        assert module.qualified_name == "com.example.models"
        assert module.language_type == LanguageType.JAVA
        assert module.sub_modules == []
        assert module.declared_types == []

    def test_module_with_sub_modules(self) -> None:
        module = Module(
            id="mod1",
            name="models",
            qualified_name="com.example.models",
            path="/src/com/example/models",
            language_type=LanguageType.JAVA,
            sub_modules=["mod2", "mod3"],
            declared_types=["type1"],
        )
        assert module.sub_modules == ["mod2", "mod3"]
        assert module.declared_types == ["type1"]

    def test_module_missing_required_field(self) -> None:
        with pytest.raises(ValidationError):
            Module(id="mod1", name="models")  # type: ignore[call-arg]


class TestType:
    """Tests for Type model."""

    def test_create_class_type(self) -> None:
        type_def = Type(
            id="type1",
            name="User",
            qualified_name="com.example.models.User",
            kind=TypeKind.CLASS,
            language_type=LanguageType.JAVA,
        )
        assert type_def.id == "type1"
        assert type_def.kind == TypeKind.CLASS
        assert type_def.modifiers == []
        assert type_def.extends == []
        assert type_def.implements == []

    def test_create_interface_type(self) -> None:
        type_def = Type(
            id="type2",
            name="Repository",
            qualified_name="com.example.Repository",
            kind=TypeKind.INTERFACE,
            language_type=LanguageType.JAVA,
            modifiers=["public", "abstract"],
        )
        assert type_def.kind == TypeKind.INTERFACE
        assert type_def.modifiers == ["public", "abstract"]

    def test_create_go_struct(self) -> None:
        type_def = Type(
            id="type3",
            name="Config",
            qualified_name="github.com/example/pkg.Config",
            kind=TypeKind.STRUCT,
            language_type=LanguageType.GO,
            embeds=["type4"],
        )
        assert type_def.kind == TypeKind.STRUCT
        assert type_def.language_type == LanguageType.GO
        assert type_def.embeds == ["type4"]


class TestCallable:
    """Tests for Callable model."""

    def test_create_method(self) -> None:
        method = Callable(
            id="call1",
            name="save",
            qualified_name="com.example.User.save",
            kind=CallableKind.METHOD,
            language_type=LanguageType.JAVA,
            signature="save()",
        )
        assert method.id == "call1"
        assert method.kind == CallableKind.METHOD
        assert method.is_static is False
        assert method.visibility == Visibility.PUBLIC
        assert method.calls == []

    def test_create_static_method(self) -> None:
        method = Callable(
            id="call2",
            name="getInstance",
            qualified_name="com.example.Singleton.getInstance",
            kind=CallableKind.METHOD,
            language_type=LanguageType.JAVA,
            signature="getInstance()",
            is_static=True,
            visibility=Visibility.PUBLIC,
        )
        assert method.is_static is True

    def test_create_constructor(self) -> None:
        ctor = Callable(
            id="call3",
            name="User",
            qualified_name="com.example.User.<init>",
            kind=CallableKind.CONSTRUCTOR,
            language_type=LanguageType.JAVA,
            signature="User(String)",
        )
        assert ctor.kind == CallableKind.CONSTRUCTOR

    def test_callable_with_calls(self) -> None:
        method = Callable(
            id="call4",
            name="process",
            qualified_name="com.example.Service.process",
            kind=CallableKind.METHOD,
            language_type=LanguageType.JAVA,
            signature="process()",
            calls=["call1", "call2"],
            return_type="type1",
        )
        assert method.calls == ["call1", "call2"]
        assert method.return_type == "type1"


class TestSymbolTable:
    """Tests for SymbolTable model."""

    def test_create_empty_symbol_table(self) -> None:
        st = SymbolTable()
        assert st.type_map == {}
        assert st.callable_map == {}

    def test_symbol_table_with_mappings(self) -> None:
        st = SymbolTable(
            type_map={"User": ["com.example.User", "com.other.User"]},
            callable_map={"save": ["com.example.User.save"]},
        )
        assert "User" in st.type_map
        assert len(st.type_map["User"]) == 2


class TestUnresolvedReference:
    """Tests for UnresolvedReference model."""

    def test_create_unresolved_reference(self) -> None:
        ref = UnresolvedReference(
            source_callable="call1",
            target_name="unknownMethod",
            reason="Target not found in symbol table",
        )
        assert ref.source_callable == "call1"
        assert ref.target_name == "unknownMethod"
        assert ref.context is None

    def test_unresolved_reference_with_context(self) -> None:
        ref = UnresolvedReference(
            source_callable="call1",
            target_name="process",
            context="Variable type: Service",
            reason="Ambiguous reference",
        )
        assert ref.context == "Variable type: Service"


class TestIR:
    """Tests for IR model."""

    def test_create_empty_ir(self) -> None:
        ir = IR(language_type=LanguageType.JAVA)
        assert ir.version == "1.0"
        assert ir.language_type == LanguageType.JAVA
        assert ir.modules == {}
        assert ir.types == {}
        assert ir.callables == {}
        assert ir.unresolved == []

    def test_create_ir_with_entities(self) -> None:
        module = Module(
            id="mod1",
            name="models",
            qualified_name="com.example.models",
            path="/src",
            language_type=LanguageType.JAVA,
        )
        type_def = Type(
            id="type1",
            name="User",
            qualified_name="com.example.models.User",
            kind=TypeKind.CLASS,
            language_type=LanguageType.JAVA,
        )
        ir = IR(
            language_type=LanguageType.JAVA,
            modules={"mod1": module},
            types={"type1": type_def},
        )
        assert "mod1" in ir.modules
        assert "type1" in ir.types

    def test_ir_merge(self) -> None:
        ir1 = IR(
            language_type=LanguageType.JAVA,
            modules={
                "mod1": Module(
                    id="mod1",
                    name="a",
                    qualified_name="a",
                    path="/a",
                    language_type=LanguageType.JAVA,
                )
            },
        )
        ir2 = IR(
            language_type=LanguageType.JAVA,
            modules={
                "mod2": Module(
                    id="mod2",
                    name="b",
                    qualified_name="b",
                    path="/b",
                    language_type=LanguageType.JAVA,
                )
            },
        )
        merged = ir1.merge(ir2)
        assert "mod1" in merged.modules
        assert "mod2" in merged.modules
        assert len(merged.modules) == 2
