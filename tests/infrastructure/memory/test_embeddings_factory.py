from src.agent.infrastructure.memory.embeddings_factory import create_embedding_adapter


def test_create_embedding_adapter_default():
    adapter = create_embedding_adapter()
    assert adapter is not None
    assert hasattr(adapter, "embed")
