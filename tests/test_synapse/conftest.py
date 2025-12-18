"""Shared pytest fixtures for Synapse tests."""

import os

import pytest
from dotenv import load_dotenv
from hypothesis import settings

# Load environment variables from .env file
load_dotenv()

# Configure hypothesis for property-based testing
settings.register_profile("ci", max_examples=100, deadline=None)
settings.register_profile("dev", max_examples=20, deadline=None)
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
