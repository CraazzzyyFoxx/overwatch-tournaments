import pytest
from cashews import cache


@pytest.fixture(autouse=True, scope="session")
def setup_test_cache():
    cache.setup("mem://", prefix="fastapi:")
    cache.setup("mem://", prefix="backend:")
