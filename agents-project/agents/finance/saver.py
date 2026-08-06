import time

from langgraph.checkpoint.memory import MemorySaver


class BoundedMemorySaver(MemorySaver):
    """MemorySaver 带线程数上限和 TTL 自动淘汰，防止 OOM。"""

    def __init__(self, max_threads: int = 50, ttl_seconds: int = 1800):
        super().__init__()
        self.max_threads = max_threads
        self.ttl_seconds = ttl_seconds
        self._created_at: dict[str, float] = {}

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id = config["configurable"]["thread_id"]
        if thread_id not in self._created_at:
            self._created_at[thread_id] = time.time()
        self._evict()
        return super().put(config, checkpoint, metadata, new_versions)

    def _evict(self):
        now = time.time()
        # TTL 淘汰
        for tid in list(self._created_at.keys()):
            if now - self._created_at[tid] > self.ttl_seconds:
                self._created_at.pop(tid, None)
                self.storage.pop(tid, None)
                self.writes.pop(tid, None)
        # 超上限时淘汰最旧的
        while len(self._created_at) > self.max_threads:
            oldest = min(self._created_at, key=lambda t: self._created_at[t])
            self._created_at.pop(oldest, None)
            self.storage.pop(oldest, None)
            self.writes.pop(oldest, None)
