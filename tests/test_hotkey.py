import pytest

from quickpick.hotkey import Hotkey, parse_hotkey


def test_parses_modifiers_and_key():
    # MOD_ALT=0x1, MOD_CONTROL=0x2; VK_SPACE=0x20
    assert parse_hotkey("ctrl+alt+space") == Hotkey(modifiers=0x3, vk=0x20)


@pytest.mark.parametrize("spec", ["ctrl+alt+bogus", "hyper+space", "space", "ctrl+alt+"])
def test_rejects_malformed_spec(spec):
    with pytest.raises(ValueError, match="hotkey"):
        parse_hotkey(spec)


def test_parses_greenshot_style_keys_that_may_lack_a_modifier():
    # VK_SNAPSHOT=0x2C; MOD_CONTROL|MOD_SHIFT=0x6
    assert parse_hotkey("PrintScreen", require_modifier=False) == Hotkey(modifiers=0, vk=0x2C)
    assert parse_hotkey("Shift + Ctrl + PrintScreen") == Hotkey(modifiers=0x6, vk=0x2C)
