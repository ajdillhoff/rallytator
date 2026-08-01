"""Job manager (ADR-0001): owns the warm Worker subprocess and bridges its queue-based
progress/results to the API's asyncio world (await for short ops, WebSocket for `track`).

The manager is the *only* DB writer for model output — the worker stays pure compute.

Two modes:
  * default — spawn `worker.run_worker` in a `spawn` subprocess (real GPU models);
  * `local_runner` — run jobs inline in a thread (tests inject a fake Registry, no GPU).
Both feed the identical `{id,type,...}` message path, so the async surface is uniform.
"""

from __future__ import annotations

import asyncio
import itertools
import multiprocessing as mp
import threading
from collections.abc import Callable
from typing import Any

from .worker import run_worker

LocalRunner = Callable[[dict, Callable[[float, str], None]], dict]


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._results: dict[str, Any] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._ids = itertools.count(1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._local: LocalRunner | None = None
        self._proc: mp.process.BaseProcess | None = None
        self._in_q = None
        self._out_q = None

    # ---- lifecycle --------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop, local_runner: LocalRunner | None = None) -> None:
        self._loop = loop
        self._local = local_runner
        if local_runner is None:
            ctx = mp.get_context("spawn")
            self._in_q = ctx.Queue()
            self._out_q = ctx.Queue()
            self._proc = ctx.Process(target=run_worker, args=(self._in_q, self._out_q), daemon=True)
            self._proc.start()
            threading.Thread(target=self._reader, daemon=True).start()

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._in_q.put(None)  # shutdown sentinel
                self._proc.join(timeout=2)
            finally:
                if self._proc.is_alive():
                    self._proc.terminate()

    # ---- submit / await ---------------------------------------------------

    def submit(self, op: str, **payload: Any) -> str:
        jid = f"job-{next(self._ids)}"
        job = {"id": jid, "op": op, **payload}
        self._jobs[jid] = {"job_id": jid, "state": "queued", "progress": 0.0}
        self._events[jid] = asyncio.Event()
        if self._local is not None:
            threading.Thread(target=self._run_local, args=(job,), daemon=True).start()
        else:
            self._in_q.put(job)
        return jid

    async def await_result(self, jid: str) -> Any:
        await self._events[jid].wait()
        st = self._jobs[jid]
        if st["state"] == "error":
            raise RuntimeError(st.get("error", "job failed"))
        return self._results.get(jid)

    def status(self, jid: str) -> dict | None:
        return self._jobs.get(jid)

    def subscribe(self, jid: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(jid, []).append(q)
        if jid in self._jobs:            # deliver current state immediately
            q.put_nowait(dict(self._jobs[jid]))
        return q

    def unsubscribe(self, jid: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(jid)
        if subs and q in subs:
            subs.remove(q)

    # ---- internals --------------------------------------------------------

    def _run_local(self, job: dict) -> None:
        jid = job["id"]
        loop = self._loop
        assert loop is not None

        def emit(p: float, d: str) -> None:
            loop.call_soon_threadsafe(self._handle, {"id": jid, "type": "progress", "progress": p, "detail": d})
        try:
            data = self._local(job, emit)  # type: ignore[misc]
            loop.call_soon_threadsafe(self._handle, {"id": jid, "type": "result", "data": data})
        except Exception as exc:  # noqa: BLE001 - job error boundary -> reported as job error
            loop.call_soon_threadsafe(self._handle, {"id": jid, "type": "error", "error": f"{type(exc).__name__}: {exc}"})

    def _reader(self) -> None:  # pragma: no cover - subprocess path
        while True:
            msg = self._out_q.get()
            if msg is None:
                return
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._handle, msg)

    def _handle(self, msg: dict) -> None:
        jid = msg["id"]
        st = self._jobs.get(jid)
        if st is None:
            return
        kind = msg["type"]
        if kind == "progress":
            st.update(state="running", progress=msg["progress"], detail=msg.get("detail"))
        elif kind == "result":
            st.update(state="done", progress=1.0)
            self._results[jid] = msg["data"]
            self._events[jid].set()
        elif kind == "error":
            st.update(state="error", error=msg.get("error"))
            self._events[jid].set()
        for q in self._subs.get(jid, []):
            q.put_nowait(dict(st))
