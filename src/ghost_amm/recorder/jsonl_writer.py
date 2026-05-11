from __future__ import annotations

from pathlib import Path
from typing import TextIO

from ghost_amm.events import Event


class RotatingJsonlEventWriter:
    def __init__(
        self,
        path: str | Path,
        *,
        rotate_every_events: int | None = None,
        rotate_every_bytes: int | None = None,
        flush_every_events: int = 1,
    ) -> None:
        self.path = Path(path)
        self.rotate_every_events = rotate_every_events
        self.rotate_every_bytes = rotate_every_bytes
        self.flush_every_events = max(flush_every_events, 1)
        self.total_events = 0
        self.current_events = 0
        self.current_bytes = 0
        self.file_index = 0
        self.paths: list[Path] = []
        self._fh: TextIO | None = None

    def __enter__(self) -> "RotatingJsonlEventWriter":
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def current_path(self) -> Path:
        if self.file_index == 0:
            return self.path
        return self.path.with_name(f"{self.path.stem}_{self.file_index:04d}{self.path.suffix}")

    def open(self) -> None:
        if self._fh is not None:
            return
        path = self.current_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.append(path)
        self._fh = path.open("w", encoding="utf-8", newline="\n")
        self.current_events = 0
        self.current_bytes = 0

    def write(self, event: Event) -> None:
        self.open()
        assert self._fh is not None
        line = event.to_json() + "\n"
        encoded_len = len(line.encode("utf-8"))
        if self._should_rotate_before_write(encoded_len):
            self._rotate()
            assert self._fh is not None
        self._fh.write(line)
        self.total_events += 1
        self.current_events += 1
        self.current_bytes += encoded_len
        if self.total_events % self.flush_every_events == 0:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is None:
            return
        self._fh.flush()
        self._fh.close()
        self._fh = None

    def _should_rotate_before_write(self, next_bytes: int) -> bool:
        if self.current_events == 0:
            return False
        if self.rotate_every_events is not None and self.current_events >= self.rotate_every_events:
            return True
        if self.rotate_every_bytes is not None and self.current_bytes + next_bytes > self.rotate_every_bytes:
            return True
        return False

    def _rotate(self) -> None:
        self.close()
        self.file_index += 1
        self.open()
