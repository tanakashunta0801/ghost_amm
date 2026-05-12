from ghost_amm.system_sleep import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, SystemSleepPreventer


def test_system_sleep_preventer_is_disabled_by_default_request() -> None:
    calls = []

    with SystemSleepPreventer(enabled=False, platform="win32", set_execution_state=calls.append) as status:
        assert not status.active
        assert status.reason == "disabled"

    assert calls == []


def test_system_sleep_preventer_uses_windows_execution_state_and_restores() -> None:
    calls = []

    def setter(flags: int) -> int:
        calls.append(flags)
        return 1

    with SystemSleepPreventer(enabled=True, platform="win32", set_execution_state=setter) as status:
        assert status.active
        assert status.reason is None

    assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS]


def test_system_sleep_preventer_reports_unsupported_platform() -> None:
    calls = []

    with SystemSleepPreventer(enabled=True, platform="linux", set_execution_state=calls.append) as status:
        assert not status.active
        assert status.reason == "unsupported_platform"

    assert calls == []


def test_system_sleep_preventer_reports_windows_failure() -> None:
    calls = []

    def setter(flags: int) -> int:
        calls.append(flags)
        return 0

    with SystemSleepPreventer(enabled=True, platform="win32", set_execution_state=setter) as status:
        assert not status.active
        assert status.reason == "set_thread_execution_state_failed"

    assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]
