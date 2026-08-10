from src.agent.application import requests as main


def test_handle_input_basic():
    result = main.handle_input("hello")
    assert "hello" in result
