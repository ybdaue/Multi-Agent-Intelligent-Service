from langgraph.checkpoint.memory import MemorySaver
from collections import OrderedDict

class BoundedMemorySaver(MemorySaver):
    def __init__(self, max_threads: int = 10):
        super().__init__()
        self.max_threads = max_threads
        self._order = OrderedDict()

    def _touch(self, thread_id: str):
        self._order.pop(thread_id, None)
        self._order[thread_id] = True
        while len(self._order) > self.max_threads:
            old_thread_id, _ = self._order.popitem(last=False)
            self.storage.pop(old_thread_id, None)

    async def aget_state(self, config):
        self._touch(config["configurable"]["thread_id"])
        return await super().aget_state(config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        self._touch(config["configurable"]["thread_id"])
        return await super().aput(config, checkpoint, metadata, new_versions)