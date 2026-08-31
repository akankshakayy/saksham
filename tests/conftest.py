import os

import pytest_asyncio

from app.config.settings import get_settings
from app.memory.database import close_database, init_database, reset_database

TEST_API_KEY = "test-secret-key-12345"


@pytest_asyncio.fixture(autouse=True)
async def setup_test_database(tmp_path):
    """Set up a temporary SQLite database for each test.

    Ensures clean state:
    - Fresh database
    - Fresh background worker (no orphaned tasks)
    - API keys configured
    """
    reset_database()
    db_path = str(tmp_path / "test.db")
    await init_database(f"sqlite+aiosqlite:///{db_path}")

    os.environ["API_KEYS_RAW"] = TEST_API_KEY
    get_settings.cache_clear()

    yield

    # Shut down background worker before closing database
    # to prevent tasks from accessing a closed connection
    from app.worker.background import get_worker, reset_worker

    worker = get_worker()
    await worker.shutdown(timeout=2.0)
    reset_worker()

    await close_database()
    reset_database()
    os.environ.pop("API_KEYS_RAW", None)
    get_settings.cache_clear()
