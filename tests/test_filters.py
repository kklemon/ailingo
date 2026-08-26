from ailingo.ingest.filters import clean_text, detect_language, is_human_prompt, prepare


def test_system_tags_are_not_human():
    assert not is_human_prompt("<task-notification>\n<task-id>x</task-id></task-notification>")
    assert not is_human_prompt("<command-name>/commit</command-name>")
    assert not is_human_prompt("/commit")
    assert not is_human_prompt("[Request interrupted by user]")
    assert not is_human_prompt("   ")


def test_human_prompt_with_reminder_prefix():
    assert is_human_prompt("<system-reminder>ctx</system-reminder>\nPlease fix the login bug")


def test_clean_text_strips_code_and_urls():
    raw = "Fix this:\n```py\nprint(1)\n```\nsee https://example.com and `foo()` please"
    cleaned = clean_text(raw)
    assert "print(1)" not in cleaned
    assert "https://" not in cleaned
    assert "[code]" in cleaned and "[url]" in cleaned
    assert cleaned.startswith("Fix this:")


def test_clean_text_truncates_long_input():
    raw = "word " * 2000
    assert len(clean_text(raw)) < 1500


def test_detect_language():
    assert detect_language("Please add a test for the login flow and fix the bug") == "en"
    assert detect_language("Bitte füge einen Test für den Login hinzu und behebe den Fehler") == "de"
    assert detect_language("fix it") == "en"


def test_prepare_filters_short_and_tags():
    assert prepare("ok") is None
    assert prepare("<local-command-stdout>foo</local-command-stdout>") is None
    result = prepare("Make the header sticky when scrolling down please")
    assert result is not None
    text, lang = result
    assert lang == "en" and "sticky" in text
