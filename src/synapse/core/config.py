"""Global configuration for Synapse.

This module provides centralized configuration management with support for
environment variables and sensible defaults.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class SynapseConfig(BaseSettings):
    """Synapse configuration settings.

    Values can be overridden via environment variables with SYNAPSE_ prefix.
    Example: SYNAPSE_ID_LENGTH=20 overrides id_length.
    """

    # ID generation
    id_length: int = Field(
        default=16,
        ge=8,
        le=64,
        description="Length of generated entity IDs (hex characters)",
    )

    # Query defaults
    default_page_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Default page size for paginated queries",
    )
    default_max_depth: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Default maximum depth for graph traversals",
    )

    # Neo4j connection
    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j connection URI",
    )
    neo4j_username: str = Field(
        default="neo4j",
        description="Neo4j username",
    )
    neo4j_password: str = Field(
        default="",
        description="Neo4j password",
    )
    neo4j_database: str = Field(
        default="neo4j",
        description="Neo4j database name",
    )

    # Connection pool
    neo4j_max_connection_lifetime: int = Field(
        default=3600,
        description="Maximum connection lifetime in seconds",
    )
    neo4j_max_connection_pool_size: int = Field(
        default=50,
        description="Maximum connection pool size",
    )
    neo4j_connection_timeout: int = Field(
        default=30,
        description="Connection timeout in seconds",
    )

    model_config = {
        "env_prefix": "SYNAPSE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_config() -> SynapseConfig:
    """Get cached configuration instance.

    Returns:
        SynapseConfig singleton instance.
    """
    return SynapseConfig()


def reload_config() -> SynapseConfig:
    """Reload configuration (clears cache).

    Returns:
        Fresh SynapseConfig instance.
    """
    get_config.cache_clear()
    return get_config()
