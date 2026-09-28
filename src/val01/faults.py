"""Link-level fault injection.

FaultyTransport wraps any Transport and corrupts traffic in the ways a real
serial link fails. It picks one fault per transaction (one write() followed
by its reads), either from a script (deterministic tests) or at random
from a seeded RNG (soak tests).

The random mode assumes the whole response is available right after
write(), which holds for SimTransport. On real hardware the link produces
its own faults.
"""

from __future__ import annotations

import random
from collections import Counter
from enum import Enum
from typing import Iterable

from .transport import Transport


class Fault(Enum):
    NONE = "none"
    FLIP_REQ = "flip_req"  # single bit flip in request, SOF excluded
    FLIP_RSP = "flip_rsp"  # single bit flip in response, SOF excluded
    TRUNCATE_RSP = "truncate_rsp"  # response loses its tail
    DROP_RSP = "drop_rsp"  # no response at all


class FaultyTransport(Transport):
    def __init__(
        self,
        inner: Transport,
        script: Iterable[Fault] | None = None,
        rate: float = 0.0,
        seed: int = 0,
    ):
        self.inner = inner
        self._script = list(script) if script is not None else None
        self.rate = rate
        self.rng = random.Random(seed)
        self.injected: Counter[Fault] = Counter()
        self._rx = bytearray()

    def _next_fault(self) -> Fault:
        if self._script is not None:
            return self._script.pop(0) if self._script else Fault.NONE
        if self.rng.random() < self.rate:
            return self.rng.choice([f for f in Fault if f is not Fault.NONE])
        return Fault.NONE

    def _flip(self, data: bytes) -> bytes:
        buf = bytearray(data)
        i = self.rng.randrange(1, len(buf))  # keep SOF intact
        buf[i] ^= 1 << self.rng.randrange(8)
        return bytes(buf)

    def write(self, data: bytes) -> None:
        fault = self._next_fault()
        self.injected[fault] += 1
        if fault is Fault.FLIP_REQ:
            data = self._flip(data)
        self.inner.write(data)

        rsp = self.inner.read(4096)
        if rsp and fault is Fault.FLIP_RSP:
            rsp = self._flip(rsp)
        elif rsp and fault is Fault.TRUNCATE_RSP:
            rsp = rsp[: self.rng.randrange(len(rsp))]
        elif fault is Fault.DROP_RSP:
            rsp = b""
        self._rx += rsp

    def read(self, n: int) -> bytes:
        chunk, self._rx = bytes(self._rx[:n]), self._rx[n:]
        return chunk

    def flush_input(self) -> None:
        self._rx.clear()
        self.inner.flush_input()

    def close(self) -> None:
        self.inner.close()
