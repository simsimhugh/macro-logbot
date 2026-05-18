"""pytest 공통 픽스처."""

import pytest
from fastapi.testclient import TestClient

from macro_logbot.app import app


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient 픽스처."""
    return TestClient(app)
