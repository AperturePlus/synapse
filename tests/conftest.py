"""Shared pytest fixtures for Synapse tests."""

import pytest
from hypothesis import settings

# Configure hypothesis for property-based testing
settings.register_profile("ci", max_examples=100)
settings.register_profile("dev", max_examples=20)
settings.load_profile("dev")


@pytest.fixture
def sample_project_id() -> str:
    """Provide a sample project ID for testing."""
    return "test-project-001"


@pytest.fixture
def sample_project_path(tmp_path) -> str:
    """Provide a temporary project path for testing."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return str(project_dir)
