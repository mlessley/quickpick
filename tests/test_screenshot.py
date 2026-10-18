from datetime import datetime
from pathlib import Path

import pytest

from quickpick.screenshot import (
    GreenshotSettings,
    capture_name,
    find_new_image,
    list_files,
    parse_greenshot_ini,
    rename_capture,
)

GREENSHOT_INI = """\ufeff; Greenshot core configuration
[Core]
RegionHotkey=PrintScreen
WindowHotkey=Alt + PrintScreen
Destinations=FileNoDialog
OutputFilePath=C:\\Users\\me\\.quickpick-data\\screenshots

[Editor]
OutputFilePath=C:\\elsewhere
"""


def test_reads_region_hotkey_and_output_folder_from_core_section():
    assert parse_greenshot_ini(GREENSHOT_INI) == GreenshotSettings(
        region_hotkey="PrintScreen",
        output_dir=Path("C:/Users/me/.quickpick-data/screenshots"),
    )


def test_finds_the_image_that_appeared_after_the_snapshot(tmp_path):
    (tmp_path / "earlier.png").write_bytes(b"")
    before = list_files(tmp_path)
    (tmp_path / "quick-copy.txt").write_text("")
    (tmp_path / "2026-10-14 09_45_00-Jira.png").write_bytes(b"")

    assert find_new_image(tmp_path, before) == tmp_path / "2026-10-14 09_45_00-Jira.png"


def test_no_new_image_yet(tmp_path):
    (tmp_path / "earlier.png").write_bytes(b"")

    assert find_new_image(tmp_path, list_files(tmp_path)) is None


STARTED = datetime(2026, 10, 18, 12, 2, 38)


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ("Untitled - Paint", "2026-10-18 12_02_38-Untitled - Paint.png"),
        (r'a\b/c:d*e?f"g<h>i|j', "2026-10-18 12_02_38-a_b_c_d_e_f_g_h_i_j.png"),
        ("", "2026-10-18 12_02_38.png"),
        ("  ", "2026-10-18 12_02_38.png"),
        ("x" * 100, f"2026-10-18 12_02_38-{'x' * 80}.png"),
        ("ends with dots...", "2026-10-18 12_02_38-ends with dots.png"),
    ],
)
def test_names_a_capture_from_its_time_and_capture_context(context, expected):
    assert capture_name(STARTED, context, ".png") == expected


def test_renames_greenshots_file_after_the_capture_context(tmp_path):
    image = tmp_path / "2026-10-18 12_02_38-2026-10-18 11_57_23-config - Notepad.png.png"
    image.write_bytes(b"png")

    renamed = rename_capture(image, STARTED, "Untitled - Paint")

    assert renamed == tmp_path / "2026-10-18 12_02_38-Untitled - Paint.png"
    assert renamed.read_bytes() == b"png"
    assert not image.exists()


def test_a_taken_name_gets_a_number(tmp_path):
    (tmp_path / "2026-10-18 12_02_38-Paint.png").write_bytes(b"first")
    image = tmp_path / "greenshot.png"
    image.write_bytes(b"second")

    assert rename_capture(image, STARTED, "Paint") == tmp_path / "2026-10-18 12_02_38-Paint (2).png"


def test_an_already_right_name_is_left_alone(tmp_path):
    image = tmp_path / "2026-10-18 12_02_38-Paint.png"
    image.write_bytes(b"png")

    assert rename_capture(image, STARTED, "Paint") == image


def test_keeps_greenshots_name_when_the_file_cant_be_renamed(tmp_path):
    missing = tmp_path / "gone.png"

    assert rename_capture(missing, STARTED, "Paint") == missing
