from __future__ import annotations

from ghost_amm.events import Event
from ghost_amm.execution.live_gates import live_order_blocked_event
from ghost_amm.execution.order_state import OrderIntent


class BitbankPaperExecutor:
    """Paper/private placeholder: virtual-only until the live gate path is explicitly enabled."""

    def submit(self, intent: OrderIntent, *, ts_ms: float, reason: str = "paper_private_post_mvp_disabled") -> Event:
        return live_order_blocked_event(intent, result=type("Result", (), {"reason": reason})(), ts_ms=ts_ms)
