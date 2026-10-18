import pytest

from quickpick.browser import choose_browser


@pytest.mark.parametrize(
    ("default", "alternate", "expected"),
    [
        ("edge", False, "edge"),
        ("edge", True, "chrome"),
        ("chrome", False, "chrome"),
        ("chrome", True, "edge"),
    ],
)
def test_enter_uses_the_default_and_ctrl_enter_the_other(default, alternate, expected):
    assert choose_browser(default, alternate) == expected
