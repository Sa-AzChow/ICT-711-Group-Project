from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Thread
from time import perf_counter
from typing import Any, Callable, DefaultDict, Dict, List, Type


EventHandler = Callable[[Any], None]


@dataclass(slots=True)
class BrokerStats:
    published: int = 0
    handled: int = 0
    dispatch_errors: int = 0
    total_dispatch_time_ms: float = 0.0

    @property
    def avg_dispatch_time_ms(self) -> float:
        if self.handled == 0:
            return 0.0
        return self.total_dispatch_time_ms / self.handled


class DomainBroker:
    """Simple asynchronous in-memory broker for event-driven simulation."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._queue: Queue[Any] = Queue()
        self._subscribers: DefaultDict[Type[Any], List[EventHandler]] = defaultdict(list)
        self._running = Event()
        self._thread: Thread | None = None
        self.stats = BrokerStats()

    def subscribe(self, event_type: Type[Any], handler: EventHandler) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        self.stats.published += 1
        self._queue.put(event)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = Thread(target=self._run_loop, daemon=True, name=f"{self.name}-broker")
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def join(self) -> None:
        self._queue.join()

    def _run_loop(self) -> None:
        while self._running.is_set() or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                handlers = self._subscribers.get(type(event), [])
                if not handlers:
                    self._queue.task_done()
                    continue
                for handler in handlers:
                    start = perf_counter()
                    try:
                        handler(event)
                    except Exception:
                        self.stats.dispatch_errors += 1
                    finally:
                        elapsed_ms = (perf_counter() - start) * 1000
                        self.stats.handled += 1
                        self.stats.total_dispatch_time_ms += elapsed_ms
                self._queue.task_done()
            except Exception:
                self.stats.dispatch_errors += 1
                self._queue.task_done()


class BrokerBridge:
    """Cross-domain bridge used when separate domain brokers are introduced."""

    def __init__(self, source: DomainBroker, target: DomainBroker) -> None:
        self.source = source
        self.target = target
        self.forwarded: Dict[str, int] = defaultdict(int)

    def forward(self, source_type: Type[Any], mapper: Callable[[Any], Any]) -> None:
        def _handler(event: Any) -> None:
            mapped = mapper(event)
            self.forwarded[type(event).__name__] += 1
            self.target.publish(mapped)

        self.source.subscribe(source_type, _handler)

