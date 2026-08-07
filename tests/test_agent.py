from src.agent import main


def test_handle_input_basic():
    assert main.handle_input("hello") == "hello"
