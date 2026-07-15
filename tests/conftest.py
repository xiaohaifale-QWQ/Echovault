"""Shared Qt lifetime management for the Windows/offscreen test suite."""

import pytest

from tests.qt_test_app import ensure_app


@pytest.fixture(scope="session", autouse=True)
def _keep_qt_application_alive():
    app = ensure_app()
    yield app
