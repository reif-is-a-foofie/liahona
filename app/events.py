import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional


class EventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subs.get(project_id, [])) + list(self._subs.get("*", []))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop if slow consumer
                pass

    async def subscribe(self, project_id: Optional[str] = None, maxsize: int = 100) -> AsyncGenerator[Dict[str, Any], None]:
        topic = project_id or "*"
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._subs.setdefault(topic, []).append(queue)

        try:
            while True:
                item = await queue.get()
                yield item
        finally:
            async with self._lock:
                lst = self._subs.get(topic, [])
                if queue in lst:
                    lst.remove(queue)


bus = EventBus()

