from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class GPUStageScheduler:
    _lock = threading.RLock()
    _owner = ""

    @classmethod
    @contextmanager
    def stage(cls, name: str):
        stage_name = str(name or "gpu-stage").strip() or "gpu-stage"
        wait_started = time.perf_counter()
        cls._lock.acquire()
        wait_elapsed = time.perf_counter() - wait_started
        previous_owner = cls._owner
        cls._owner = stage_name
        try:
            if wait_elapsed >= 0.05:
                print(
                    f"[GPU Scheduler] Stage '{stage_name}' waited {wait_elapsed:.2f}s "
                    f"for '{previous_owner or 'idle'}'"
                )
            yield
        finally:
            cls._owner = ""
            cls._lock.release()
