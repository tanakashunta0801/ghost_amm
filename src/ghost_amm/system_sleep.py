from __future__ import annotations

import ctypes
import sys
from dataclasses import asdict, dataclass
from typing import Callable


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


SetExecutionState = Callable[[int], int]


@dataclass
class SleepPreventionStatus:
    enabled: bool
    active: bool
    reason: str | None
    platform: str

    def to_dict(self) -> dict:
        return asdict(self)


class SystemSleepPreventer:
    def __init__(
        self,
        *,
        enabled: bool,
        platform: str | None = None,
        set_execution_state: SetExecutionState | None = None,
    ) -> None:
        self.enabled = enabled
        self.platform = platform or sys.platform
        self._set_execution_state = set_execution_state
        self.status = SleepPreventionStatus(enabled=enabled, active=False, reason=None, platform=self.platform)

    def __enter__(self) -> SleepPreventionStatus:
        if not self.enabled:
            self.status = SleepPreventionStatus(False, False, "disabled", self.platform)
            return self.status
        if self.platform != "win32":
            self.status = SleepPreventionStatus(True, False, "unsupported_platform", self.platform)
            return self.status
        setter = self._set_execution_state or _windows_set_thread_execution_state
        previous = setter(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if previous == 0:
            self.status = SleepPreventionStatus(True, False, "set_thread_execution_state_failed", self.platform)
            return self.status
        self.status = SleepPreventionStatus(True, True, None, self.platform)
        return self.status

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.status.active:
            setter = self._set_execution_state or _windows_set_thread_execution_state
            setter(ES_CONTINUOUS)


def _windows_set_thread_execution_state(flags: int) -> int:
    return int(ctypes.windll.kernel32.SetThreadExecutionState(flags))  # type: ignore[attr-defined]
