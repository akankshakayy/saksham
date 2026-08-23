import pytest_asyncio

from app.memory.database import close_database, init_database, reset_database


@pytest_asyncio.fixture(autouse=True)
async def setup_test_database(tmp_path):
    """Set up a temporary SQLite database for each test."""
    reset_database()
    db_path = str(tmp_path / "test.db")
    await init_database(f"sqlite+aiosqlite:///{db_path}")
    yield
    await close_database()
    reset_database()
