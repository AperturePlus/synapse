"""Unit tests for configuration management."""

import os
from unittest.mock import patch

import pytest

from synapse.core.config import SynapseConfig, get_config, reload_config


class TestSynapseConfig:
    """Tests for SynapseConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        # Clear env and disable .env file loading
        with patch.dict(os.environ, {}, clear=True):
            config = SynapseConfig(_env_file=None)

            assert config.id_length == 16
            assert config.default_page_size == 100
            assert config.default_max_depth == 5
            assert config.batch_write_size == 1000
            assert config.neo4j_uri == "bolt://localhost:7687"
            assert config.neo4j_username == "neo4j"
            assert config.neo4j_database == "neo4j"

    def test_env_override(self) -> None:
        """Test environment variable override."""
        with patch.dict(
            os.environ,
            {
                "SYNAPSE_ID_LENGTH": "20",
                "SYNAPSE_DEFAULT_PAGE_SIZE": "50",
                "SYNAPSE_BATCH_WRITE_SIZE": "500",
            },
        ):
            config = SynapseConfig()
            assert config.id_length == 20
            assert config.default_page_size == 50
            assert config.batch_write_size == 500

    def test_validation_id_length_min(self) -> None:
        """Test ID length minimum validation."""
        with patch.dict(os.environ, {"SYNAPSE_ID_LENGTH": "5"}):
            with pytest.raises(ValueError):
                SynapseConfig()

    def test_validation_id_length_max(self) -> None:
        """Test ID length maximum validation."""
        with patch.dict(os.environ, {"SYNAPSE_ID_LENGTH": "100"}):
            with pytest.raises(ValueError):
                SynapseConfig()

    def test_validation_page_size(self) -> None:
        """Test page size validation."""
        with patch.dict(os.environ, {"SYNAPSE_DEFAULT_PAGE_SIZE": "0"}):
            with pytest.raises(ValueError):
                SynapseConfig()

        with patch.dict(os.environ, {"SYNAPSE_DEFAULT_PAGE_SIZE": "2000"}):
            with pytest.raises(ValueError):
                SynapseConfig()

    def test_validation_batch_size(self) -> None:
        """Test batch size validation."""
        with patch.dict(os.environ, {"SYNAPSE_BATCH_WRITE_SIZE": "50"}):
            with pytest.raises(ValueError):
                SynapseConfig()

        with patch.dict(os.environ, {"SYNAPSE_BATCH_WRITE_SIZE": "20000"}):
            with pytest.raises(ValueError):
                SynapseConfig()


class TestConfigCaching:
    """Tests for configuration caching."""

    def test_get_config_cached(self) -> None:
        """Test that get_config returns cached instance."""
        reload_config()  # Clear cache first
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_reload_config_clears_cache(self) -> None:
        """Test that reload_config clears cache."""
        config1 = get_config()
        config2 = reload_config()
        config3 = get_config()

        assert config1 is not config2
        assert config2 is config3
