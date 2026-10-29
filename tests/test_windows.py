from quickpick.windows import centred_in, geometry_rect, is_mostly_on_screen

LAPTOP = (0, 0, 1920, 1040)
MONITOR_4K = (1920, 0, 5760, 2120)


def test_a_window_inside_a_monitor_is_on_screen():
    assert is_mostly_on_screen((100, 100, 900, 700), [LAPTOP])


def test_a_window_left_where_a_monitor_was_is_off_screen():
    # Placed on the 4K monitor, which has since been unplugged
    assert not is_mostly_on_screen((3000, 1200, 3800, 1800), [LAPTOP])


def test_a_window_mostly_hanging_off_the_edge_is_off_screen():
    assert not is_mostly_on_screen((1700, 100, 2500, 700), [LAPTOP])


def test_a_window_mostly_on_the_screen_is_on_screen():
    assert is_mostly_on_screen((1300, 100, 2100, 700), [LAPTOP])


def test_a_window_straddling_two_monitors_is_on_screen():
    assert is_mostly_on_screen((1600, 100, 2400, 700), [LAPTOP, MONITOR_4K])


def test_centred_in_a_work_area():
    assert centred_in((1920, 0, 5760, 2120), 800, 600) == (3440, 760)


def test_geometry_rect_reads_tk_geometry():
    assert geometry_rect("800x600+300+200") == (300, 200, 1100, 800)


def test_geometry_rect_reads_negative_positions():
    assert geometry_rect("800x600+-1700+-20") == (-1700, -20, -900, 580)
