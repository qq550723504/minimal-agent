from typing import List, Any
import time


class Memory:
    """简单的内存实现：短期会话存储与检索。

    这是一个最小示例，可替换为向量DB实现。
    """

    def __init__(self):
        self._items: List[dict] = []

    def add(self, user_id: str, item: Any):
        self._items.append({
            "user_id": user_id,
            "item": item,
            "ts": time.time(),
        })

    def recent(self, user_id: str, limit: int = 5):
        results = [i for i in self._items if i["user_id"] == user_id]
        return [r["item"] for r in results[-limit:]]


_GLOBAL_MEMORY = Memory()


def get_global_memory() -> Memory:
    return _GLOBAL_MEMORY
