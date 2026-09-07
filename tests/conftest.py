import pytest

from app.tray_rate_limit import reset_tray_rate_limiter_for_tests
from app.webhooks import reset_webhooks_for_tests


@pytest.fixture(autouse=True)
def _reset_process_local_guards():
    reset_tray_rate_limiter_for_tests()
    reset_webhooks_for_tests()
    yield
    reset_tray_rate_limiter_for_tests()
    reset_webhooks_for_tests()
