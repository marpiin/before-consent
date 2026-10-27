import before_consent


def test_version_is_set():
    assert before_consent.__version__.count(".") == 2
