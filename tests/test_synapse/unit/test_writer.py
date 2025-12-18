"""Unit tests for GraphWriter."""

from unittest.mock import MagicMock, call, patch

import pytest

from synapse.core.models import (
    Callable,
    CallableKind,
    IR,
    LanguageType,
    Module,
    Type,
    TypeKind,
    Visibility,
)
from synapse.graph.writer import (
    DanglingReference,
    GraphWriter,
    WriteResult,
    _validate_identifier,
    _ALLOWED_LABELS,
    _ALLOWED_REL_TYPES,
)


class TestValidateIdentifier:
    """Tests for identifier validation."""

    def test_valid_label(self) -> None:
        """Valid label should not raise."""
        _validate_identifier("Module", _ALLOWED_LABELS, "label")

    def test_invalid_label(self) -> None:
        """Invalid label should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid label"):
            _validate_identifier("InvalidLabel", _ALLOWED_LABELS, "label")

    def test_valid_rel_type(self) -> None:
        """Valid relationship type should not raise."""
        _validate_identifier("CALLS", _ALLOWED_REL_TYPES, "relationship type")

    def test_invalid_rel_type(self) -> None:
        """Invalid relationship type should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid relationship type"):
            _validate_identifier("INVALID_REL", _ALLOWED_REL_TYPES, "relationship type")

    def test_invalid_format(self) -> None:
        """Invalid format should raise ValueError (caught by whitelist check)."""
        with pytest.raises(ValueError, match="Invalid label"):
            _validate_identifier("123Invalid", _ALLOWED_LABELS, "label")


class TestWriteResult:
    """Tests for WriteResult dataclass."""

    def test_total_nodes(self) -> None:
        """Total nodes should sum all node types."""
        result = WriteResult(modules_written=5, types_written=10, callables_written=15)
        assert result.total_nodes == 30

    def test_success_no_dangling(self) -> None:
        """Success should be True when no dangling references."""
        result = WriteResult(relationships_written=10)
        assert result.success is True

    def test_success_with_dangling(self) -> None:
        """Success should be False when dangling references exist."""
        result = WriteResult(
            relationships_written=10,
            dangling_references=[
                DanglingReference(
                    source_id="s1",
                    target_id="t1",
                    relationship_type="CALLS",
                    reason="Not found",
                )
            ],
        )
        assert result.success is False


class TestGraphWriter:
    """Tests for GraphWriter."""

    @pytest.fixture
    def mock_connection(self) -> MagicMock:
        """Create mock Neo4j connection."""
        conn = MagicMock()
        session = MagicMock()
        conn.session.return_value.__enter__.return_value = session
        return conn

    @pytest.fixture
    def writer(self, mock_connection: MagicMock) -> GraphWriter:
        """Create GraphWriter with mock connection."""
        return GraphWriter(mock_connection)

    def test_write_in_chunks_single_batch(
        self, writer: GraphWriter, mock_connection: MagicMock
    ) -> None:
        """Test chunking with data smaller than batch size."""
        query = "UNWIND $items AS i CREATE (n {id: i.id})"
        data = [{"id": f"id{i}"} for i in range(100)]

        writer._write_in_chunks(query, data, "items")

        session = mock_connection.session.return_value.__enter__.return_value
        assert session.run.call_count == 1
        session.run.assert_called_once_with(query, {"items": data})

    def test_write_in_chunks_multiple_batches(
        self, writer: GraphWriter, mock_connection: MagicMock
    ) -> None:
        """Test chunking with data larger than batch size."""
        writer._batch_size = 100
        query = "UNWIND $items AS i CREATE (n {id: i.id})"
        data = [{"id": f"id{i}"} for i in range(250)]

        writer._write_in_chunks(query, data, "items")

        session = mock_connection.session.return_value.__enter__.return_value
        assert session.run.call_count == 3
        calls = session.run.call_args_list
        assert len(calls[0][0][1]["items"]) == 100
        assert len(calls[1][0][1]["items"]) == 100
        assert len(calls[2][0][1]["items"]) == 50

    def test_write_modules_empty(
        self, writer: GraphWriter, mock_connection: MagicMock
    ) -> None:
        """Test writing empty modules."""
        ir = IR(language_type=LanguageType.JAVA)
        count = writer._write_modules(ir, "proj1")

        assert count == 0
        session = mock_connection.session.return_value.__enter__.return_value
        session.run.assert_not_called()

    def test_write_modules(
        self, writer: GraphWriter, mock_connection: MagicMock
    ) -> None:
        """Test writing modules."""
        ir = IR(
            language_type=LanguageType.JAVA,
            modules={
                "m1": Module(
                    id="m1",
                    name="pkg",
                    qualified_name="com.example.pkg",
                    path="/src/com/example/pkg",
                    language_type=LanguageType.JAVA,
                )
            },
        )

        count = writer._write_modules(ir, "proj1")

        assert count == 1
        session = mock_connection.session.return_value.__enter__.return_value
        session.run.assert_called_once()

    def test_collect_valid_ids(
        self, writer: GraphWriter, mock_connection: MagicMock
    ) -> None:
        """Test collecting valid IDs from IR and database."""
        ir = IR(
            language_type=LanguageType.JAVA,
            modules={
                "m1": Module(
                    id="m1",
                    name="mod",
                    qualified_name="com.example",
                    path="/src",
                    language_type=LanguageType.JAVA,
                )
            },
            types={
                "t1": Type(
                    id="t1",
                    name="Type1",
                    qualified_name="com.example.Type1",
                    kind=TypeKind.CLASS,
                    language_type=LanguageType.JAVA,
                )
            },
            callables={
                "c1": Callable(
                    id="c1",
                    name="method",
                    qualified_name="com.example.Type1.method",
                    kind=CallableKind.METHOD,
                    language_type=LanguageType.JAVA,
                    signature="method()",
                    visibility=Visibility.PUBLIC,
                )
            },
        )

        # Mock database query result
        session = mock_connection.session.return_value.__enter__.return_value
        session.run.return_value = [
            {"id": "db1"},
            {"id": "db2"},
            {"id": None},  # Should be filtered out
        ]

        valid_ids = writer._collect_valid_ids(ir, "proj1")

        assert valid_ids == {"m1", "t1", "c1", "db1", "db2"}

    def test_write_relationships_batch_validates_identifiers(
        self, writer: GraphWriter
    ) -> None:
        """Test that batch write validates identifiers."""
        with pytest.raises(ValueError, match="Invalid label"):
            writer._write_relationships_batch(
                [("s1", "t1")], "CALLS", "InvalidLabel", "Callable"
            )

        with pytest.raises(ValueError, match="Invalid relationship type"):
            writer._write_relationships_batch(
                [("s1", "t1")], "INVALID", "Callable", "Callable"
            )

    def test_write_ir_integration(
        self, writer: GraphWriter, mock_connection: MagicMock
    ) -> None:
        """Test full IR write integration."""
        ir = IR(
            language_type=LanguageType.JAVA,
            modules={
                "m1": Module(
                    id="m1",
                    name="pkg",
                    qualified_name="com.example.pkg",
                    path="/src",
                    language_type=LanguageType.JAVA,
                    declared_types=["t1"],
                )
            },
            types={
                "t1": Type(
                    id="t1",
                    name="MyClass",
                    qualified_name="com.example.pkg.MyClass",
                    kind=TypeKind.CLASS,
                    language_type=LanguageType.JAVA,
                    callables=["c1"],
                )
            },
            callables={
                "c1": Callable(
                    id="c1",
                    name="method",
                    qualified_name="com.example.pkg.MyClass.method",
                    kind=CallableKind.METHOD,
                    language_type=LanguageType.JAVA,
                    signature="method()",
                    visibility=Visibility.PUBLIC,
                )
            },
        )

        # Mock database query for valid IDs
        session = mock_connection.session.return_value.__enter__.return_value
        session.run.return_value = []

        result = writer.write_ir(ir, "proj1")

        assert result.modules_written == 1
        assert result.types_written == 1
        assert result.callables_written == 1
        assert result.relationships_written == 2  # DECLARES + CONTAINS
        assert len(result.dangling_references) == 0

    def test_clear_project(
        self, writer: GraphWriter, mock_connection: MagicMock
    ) -> None:
        """Test clearing project data."""
        session = mock_connection.session.return_value.__enter__.return_value
        session.run.return_value.single.return_value = {"deleted": 42}

        count = writer.clear_project("proj1")

        assert count == 42
        session.run.assert_called_once()
