import pytest

from app.config import Settings
from app.exceptions import TrayAPIError
from app.tray_rate_limit import acquire_tray_quota, reset_tray_rate_limiter_for_tests


@pytest.fixture(autouse=True)
def _reset_limiter():
    reset_tray_rate_limiter_for_tests()
    yield
    reset_tray_rate_limiter_for_tests()


def _settings(*, per_minute=2, per_day=10):
    return Settings(
        "https://tray.test/web_api",
        "code",
        "key",
        "secret",
        180,
        "687890",
        tray_rate_limit_per_minute=per_minute,
        tray_rate_limit_per_day=per_day,
    )


def test_minute_quota_raises_429():
    settings = _settings(per_minute=2, per_day=100)
    acquire_tray_quota(settings)
    acquire_tray_quota(settings)
    with pytest.raises(TrayAPIError) as error:
        acquire_tray_quota(settings)
    assert error.value.status_code == 429
    assert error.value.diagnostics.get("error_code") == "tray_rate_limited"


def test_zero_quota_disables_limiter():
    settings = _settings(per_minute=0, per_day=0)
    for _ in range(5):
        acquire_tray_quota(settings)
