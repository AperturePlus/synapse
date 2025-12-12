"""Neo4j connection management with connection pooling and retry logic.

This module provides a connection manager for Neo4j database operations,
supporting environment variable configuration and automatic retry on failures.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

if TYPE_CHECKING:
    from neo4j import Driver, Session


@dataclass
class Neo4jConfig:
    """Configuration for Neo4j connection."""

    uri: str
    username: str
    password: str
    database: str = "neo4j"
    max_connection_pool_size: int = 50
    connection_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> Neo4jConfig:
        """Create configuration from environment variables.

        Environment variables (with SYNAPSE_ prefix or without):
            SYNAPSE_NEO4J_URI or NEO4J_URI: Database URI (default: bolt://localhost:7687)
            SYNAPSE_NEO4J_USERNAME or NEO4J_USERNAME: Username (default: neo4j)
            SYNAPSE_NEO4J_PASSWORD or NEO4J_PASSWORD: Password (default: neo4j)
            SYNAPSE_NEO4J_DATABASE or NEO4J_DATABASE: Database name (default: neo4j)
            SYNAPSE_NEO4J_MAX_CONNECTION_POOL_SIZE or NEO4J_MAX_POOL_SIZE: Max pool size (default: 50)
            SYNAPSE_NEO4J_CONNECTION_TIMEOUT or NEO4J_CONNECTION_TIMEOUT: Timeout in seconds (default: 30)
        """
        return cls(
            uri=os.getenv("SYNAPSE_NEO4J_URI") or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("SYNAPSE_NEO4J_USERNAME") or os.getenv("NEO4J_USERNAME", "neo4j"),
            password=os.getenv("SYNAPSE_NEO4J_PASSWORD") or os.getenv("NEO4J_PASSWORD", "neo4j"),
            database=os.getenv("SYNAPSE_NEO4J_DATABASE") or os.getenv("NEO4J_DATABASE", "neo4j"),
            max_connection_pool_size=int(
                os.getenv("SYNAPSE_NEO4J_MAX_CONNECTION_POOL_SIZE")
                or os.getenv("NEO4J_MAX_POOL_SIZE", "50")
            ),
            connection_timeout=float(
                os.getenv("SYNAPSE_NEO4J_CONNECTION_TIMEOUT")
                or os.getenv("NEO4J_CONNECTION_TIMEOUT", "30")
            ),
        )


class ConnectionError(Exception):
    """Raised when Neo4j connection fails."""

    pass


class Neo4jConnection:
    """Neo4j connection manager with pooling and retry logic.

    This class manages the Neo4j driver lifecycle and provides session
    management with automatic retry on transient failures.

    Example:
        >>> config = Neo4jConfig.from_env()
        >>> conn = Neo4jConnection(config)
        >>> with conn.session() as session:
        ...     result = session.run("MATCH (n) RETURN count(n)")
        >>> conn.close()
    """

    def __init__(self, config: Neo4jConfig | None = None) -> None:
        """Initialize connection manager.

        Args:
            config: Neo4j configuration. If None, loads from environment.
        """
        self._config = config or Neo4jConfig.from_env()
        self._driver: Driver | None = None

    @property
    def driver(self) -> Driver:
        """Get or create the Neo4j driver."""
        if self._driver is None:
            self._driver = self._create_driver()
        return self._driver

    def _create_driver(self) -> Driver:
        """Create a new Neo4j driver instance."""
        try:
            return GraphDatabase.driver(
                self._config.uri,
                auth=(self._config.username, self._config.password),
                max_connection_pool_size=self._config.max_connection_pool_size,
                connection_timeout=self._config.connection_timeout,
            )
        except Exception as e:
            raise ConnectionError(f"Failed to create Neo4j driver: {e}") from e

    @contextmanager
    def session(self, database: str | None = None) -> Generator[Session, None, None]:
        """Get a database session with automatic cleanup.

        Args:
            database: Database name. If None, uses config default.

        Yields:
            Neo4j session instance.
        """
        db = database or self._config.database
        session = self.driver.session(database=db)
        try:
            yield session
        finally:
            session.close()

    def execute_with_retry(
        self,
        query: str,
        parameters: dict | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> list[dict]:
        """Execute a query with automatic retry on transient failures.

        Args:
            query: Cypher query string.
            parameters: Query parameters.
            max_retries: Maximum number of retry attempts.
            retry_delay: Base delay between retries (exponential backoff).

        Returns:
            List of result records as dictionaries.

        Raises:
            ConnectionError: If all retry attempts fail.
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                with self.session() as session:
                    result = session.run(query, parameters or {})
                    return [record.data() for record in result]
            except (ServiceUnavailable, SessionExpired) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = retry_delay * (2**attempt)
                    time.sleep(delay)
                    # Reset driver on connection issues
                    self._driver = None

        raise ConnectionError(
            f"Query failed after {max_retries} attempts: {last_error}"
        ) from last_error

    def verify_connectivity(self) -> bool:
        """Verify database connectivity.

        Returns:
            True if connection is successful.

        Raises:
            ConnectionError: If connection verification fails.
        """
        try:
            self.driver.verify_connectivity()
            return True
        except Exception as e:
            raise ConnectionError(f"Failed to verify connectivity: {e}") from e

    def close(self) -> None:
        """Close the driver and release resources."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> Neo4jConnection:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit with cleanup."""
        self.close()


# Global connection instance for convenience
_global_connection: Neo4jConnection | None = None


def get_connection(config: Neo4jConfig | None = None) -> Neo4jConnection:
    """Get or create a global connection instance.

    Args:
        config: Optional configuration. Only used on first call.

    Returns:
        Global Neo4jConnection instance.
    """
    global _global_connection
    if _global_connection is None:
        _global_connection = Neo4jConnection(config)
    return _global_connection


def close_connection() -> None:
    """Close the global connection if it exists."""
    global _global_connection
    if _global_connection is not None:
        _global_connection.close()
        _global_connection = None
