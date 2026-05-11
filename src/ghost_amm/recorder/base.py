from __future__ import annotations

from abc import ABC, abstractmethod


class EventRecorder(ABC):
    @abstractmethod
    async def run(self) -> None:
        ...
