import time

from server.signal_server import LoginThrottle


def test_locks_after_max_attempts():
    throttle = LoginThrottle(max_attempts=3, window=60, lockout=120)
    key = "1.2.3.4"
    assert throttle.retry_after(key) == 0
    throttle.record_failure(key)
    throttle.record_failure(key)
    assert throttle.retry_after(key) == 0
    throttle.record_failure(key)
    assert throttle.retry_after(key) > 0


def test_success_reset_clears_state():
    throttle = LoginThrottle(max_attempts=2, window=60, lockout=60)
    key = "1.2.3.4"
    throttle.record_failure(key)
    throttle.record_failure(key)
    assert throttle.retry_after(key) > 0
    throttle.reset(key)
    assert throttle.retry_after(key) == 0


def test_old_failures_leave_the_window():
    throttle = LoginThrottle(max_attempts=3, window=0.2, lockout=60)
    key = "1.2.3.4"
    throttle.record_failure(key)
    throttle.record_failure(key)
    time.sleep(0.35)
    throttle.record_failure(key)
    assert throttle.retry_after(key) == 0


def test_lockout_expires():
    throttle = LoginThrottle(max_attempts=1, window=60, lockout=0.2)
    key = "1.2.3.4"
    throttle.record_failure(key)
    assert throttle.retry_after(key) > 0
    time.sleep(0.35)
    assert throttle.retry_after(key) == 0


def test_keys_are_independent():
    throttle = LoginThrottle(max_attempts=1, window=60, lockout=60)
    throttle.record_failure("1.1.1.1")
    assert throttle.retry_after("1.1.1.1") > 0
    assert throttle.retry_after("2.2.2.2") == 0
