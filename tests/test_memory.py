from src.agent.memory import Memory


def test_memory_keeps_a_bounded_history_per_user():
    memory = Memory(max_items_per_user=2)

    memory.add("alice", {"prompt": "first"})
    memory.add("alice", {"prompt": "second"})
    memory.add("alice", {"prompt": "third"})
    memory.add("bob", {"prompt": "bob request"})

    assert memory.recent("alice", limit=5) == [{"prompt": "second"}, {"prompt": "third"}]
    assert memory.recent("bob", limit=5) == [{"prompt": "bob request"}]


def test_memory_synchronizes_add_and_recent_operations():
    class TrackingLock:
        def __init__(self):
            self.enters = 0

        def __enter__(self):
            self.enters += 1
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

    memory = Memory(max_items_per_user=2)
    lock = TrackingLock()
    memory._lock = lock

    memory.add("alice", {"prompt": "one"})
    memory.recent("alice")

    assert lock.enters == 2
