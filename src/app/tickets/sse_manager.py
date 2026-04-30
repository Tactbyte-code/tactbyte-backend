"""
src/app/tickets/sse_manager.py

In-memory pub/sub for ticket SSE streams.
One asyncio.Queue per subscriber; all subscribers on the same ticket_id
receive every broadcast (admin ↔ user both see each other's messages in
real time).
"""

import asyncio
from collections import defaultdict
from typing import Dict, Set


class TicketSSEManager:
    def __init__(self) -> None:
        self._queues: Dict[int, Set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, ticket_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues[ticket_id].add(q)
        return q

    def unsubscribe(self, ticket_id: int, q: asyncio.Queue) -> None:
        self._queues[ticket_id].discard(q)
        if not self._queues[ticket_id]:
            self._queues.pop(ticket_id, None)

    async def broadcast(self, ticket_id: int, payload: dict) -> None:
        """Push a dict payload to every subscriber (serialized once per call)."""
        queues = self._queues.get(ticket_id)
        if not queues:
            return
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow consumer — they'll resync on reconnect

    async def broadcast_raw(self, ticket_id: int, payload: dict) -> None:
        """Alias for broadcast — kept for clarity at call sites."""
        await self.broadcast(ticket_id, payload)

    def subscriber_count(self, ticket_id: int) -> int:
        return len(self._queues.get(ticket_id, set()))

    def has_subscribers(self, ticket_id: int) -> bool:
        return bool(self._queues.get(ticket_id))


sse_manager = TicketSSEManager()