from quickpick.markup import first_url, format_line, inline, split_code


def test_inline_escapes_everything_else():
    assert inline("<script>alert(1)</script> & co") == (
        "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co"
    )


def test_inline_code_is_left_unformatted():
    assert inline("run `**not bold** <x>` now") == ("run <code>**not bold** &lt;x&gt;</code> now")


def test_inline_bold_and_italic():
    assert inline("**big** and *small*") == "<strong>big</strong> and <em>small</em>"


def test_inline_stars_inside_words_are_not_italic():
    assert inline("2*3*4 and file*.txt") == "2*3*4 and file*.txt"


def test_inline_urls_become_links_opening_in_a_new_tab():
    assert inline("see https://example.com/a?b=1&c=2 now") == (
        'see <a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener '
        'noreferrer">https://example.com/a?b=1&amp;c=2</a> now'
    )


def test_inline_url_leaves_trailing_punctuation_outside_the_link():
    assert inline("(at https://example.com/x).") == (
        '(at <a href="https://example.com/x" target="_blank" rel="noopener noreferrer">'
        "https://example.com/x</a>)."
    )


def test_inline_url_keeps_its_own_brackets():
    assert 'href="https://en.wikipedia.org/wiki/Foo_(bar)"' in inline(
        "https://en.wikipedia.org/wiki/Foo_(bar)"
    )


def test_inline_only_links_web_addresses():
    assert "<a" not in inline("javascript:alert(1) file:///c:/x")


def test_inline_formats_inside_bold():
    assert inline("**see https://a.example.com**") == (
        '<strong>see <a href="https://a.example.com" target="_blank" rel="noopener noreferrer">'
        "https://a.example.com</a></strong>"
    )


def test_headings():
    assert format_line("# Plan") == '<span class="h1">Plan</span>'
    assert format_line("### Later *maybe*") == '<span class="h3">Later <em>maybe</em></span>'
    assert format_line("#project-x is a tag") == "#project-x is a tag"


def test_bullets_keep_their_indent():
    assert format_line("- one") == "• one"
    assert format_line("  * two") == "  • two"
    assert format_line("1. numbered stays") == "1. numbered stays"


def test_split_code_finds_fenced_runs_of_lines_leaving_out_the_fences():
    lines = ["before", "```mermaid", "graph TD", "  a --> b", "```", "after"]

    assert split_code(lines) == [
        ("text", range(0, 1)),
        ("code", range(2, 4)),
        ("text", range(5, 6)),
    ]


def test_split_code_runs_an_unclosed_fence_to_the_end():
    assert split_code(["```", "x: 1"]) == [("code", range(1, 2))]


def test_split_code_keeps_an_empty_code_block():
    assert split_code(["```", "```"]) == [("code", range(1, 1))]


def test_first_url_finds_the_first_web_address_without_trailing_punctuation():
    assert first_url("PR\nreview https://a.example.com/1, then https://b.example.com") == (
        "https://a.example.com/1"
    )
    assert first_url("no address here") is None
