from src.agent.memory import Memory


def test_memory_keeps_a_bounded_history_per_user():
    memory = Memory(max_items_per_user=2)

    memory.add("alice", {"prompt": "first"})
    memory.add("alice", {"prompt": "second"})
    memory.add("alice", {"prompt": "third"})
    memory.add("bob", {"prompt": "bob request"})

    assert memory.recent("alice", limit=5) == [{"prompt": "second"}, {"prompt": "third"}]
    assert memory.recent("bob", limit=5) == [{"prompt": "bob request"}]
