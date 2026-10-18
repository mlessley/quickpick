from pathlib import Path

from quickpick.screenshot import GreenshotSettings, find_new_image, list_files, parse_greenshot_ini

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
