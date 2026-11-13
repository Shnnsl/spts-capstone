from sensors import MockSensors


def test_mock_mode_imports_and_initializes_without_gpio():
    mock = MockSensors(lambda *_args, **_kwargs: None)
    assert set(mock.states) == {"S1", "S2", "S3", "S4", "S5"}
    assert all(state is False for state in mock.states.values())
