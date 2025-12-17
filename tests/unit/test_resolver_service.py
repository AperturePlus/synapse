"""Unit tests for the entity resolver service."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from synapse.core.models import LanguageType
from synapse.services.resolver_service import (
    AmbiguousCallableError,
    EntityResolverService,
)


class TestEntityResolverService:
    """Tests for EntityResolverService."""

    def test_get_module_not_found(self) -> None:
        """Returns None when module does not exist."""
        mock_conn = MagicMock()
        mock_session = MagicMock()
        mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_conn.session.return_value.__exit__ = MagicMock(return_value=None)
        mock_session.run.return_value.single.return_value = None

        service = EntityResolverService(mock_conn)
        module = service.get_module(
            project_id="p1",
            language_type=LanguageType.JAVA,
            qualified_name="com.example",
        )
        assert module is None

    def test_get_module_success(self) -> None:
        """Resolves module by composite key."""
        record = {
            "id": "m1",
            "projectId": "p1",
            "languageType": "java",
            "name": "example",
            "qualifiedName": "com.example",
            "path": "/src",
        }
        mock_conn = MagicMock()
        mock_session = MagicMock()
        mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_conn.session.return_value.__exit__ = MagicMock(return_value=None)
        mock_session.run.return_value.single.return_value = record

        service = EntityResolverService(mock_conn)
        module = service.get_module(
            project_id="p1",
            language_type=LanguageType.JAVA,
            qualified_name="com.example",
        )
        assert module is not None
        assert module.id == "m1"
        assert module.project_id == "p1"
        assert module.language_type == LanguageType.JAVA
        assert module.qualified_name == "com.example"

    def test_find_callables_success(self) -> None:
        """Finds callables (possibly multiple overloads)."""
        records = [
            {
                "id": "c1",
                "projectId": "p1",
                "languageType": "java",
                "name": "foo",
                "qualifiedName": "com.example.A.foo",
                "kind": "METHOD",
                "signature": "()V",
            },
            {
                "id": "c2",
                "projectId": "p1",
                "languageType": "java",
                "name": "foo",
                "qualifiedName": "com.example.A.foo",
                "kind": "METHOD",
                "signature": "(I)V",
            },
        ]
        mock_conn = MagicMock()
        mock_session = MagicMock()
        mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_conn.session.return_value.__exit__ = MagicMock(return_value=None)
        mock_session.run.return_value = records

        service = EntityResolverService(mock_conn)
        matches = service.find_callables(
            project_id="p1",
            language_type=LanguageType.JAVA,
            qualified_name="com.example.A.foo",
        )
        assert len(matches) == 2
        assert {m.signature for m in matches} == {"()V", "(I)V"}

    def test_resolve_callable_ambiguous(self) -> None:
        """Raises when multiple overloads exist and signature is missing."""
        records = [
            {
                "id": "c1",
                "projectId": "p1",
                "languageType": "java",
                "name": "foo",
                "qualifiedName": "com.example.A.foo",
                "kind": "METHOD",
                "signature": "()V",
            },
            {
                "id": "c2",
                "projectId": "p1",
                "languageType": "java",
                "name": "foo",
                "qualifiedName": "com.example.A.foo",
                "kind": "METHOD",
                "signature": "(I)V",
            },
        ]
        mock_conn = MagicMock()
        mock_session = MagicMock()
        mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_conn.session.return_value.__exit__ = MagicMock(return_value=None)
        mock_session.run.return_value = records

        service = EntityResolverService(mock_conn)
        with pytest.raises(AmbiguousCallableError):
            service.resolve_callable(
                project_id="p1",
                language_type=LanguageType.JAVA,
                qualified_name="com.example.A.foo",
            )

