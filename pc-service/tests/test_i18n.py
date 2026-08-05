"""The catalogues have to stay in step with each other and with the call sites.

The interesting failure mode is not a missing translation -- that falls back to
English and is merely disappointing. It is a translation whose placeholders do
not match, because ``str.format`` then raises ``KeyError`` in the middle of
printing, turning a cosmetic problem into a crash.
"""

from __future__ import annotations

import re

import pytest

from wol_unlock import i18n
from wol_unlock.i18n import CATALOGS, EN, RU, detect_locale

PLACEHOLDER = re.compile(r"\{(\w+)")


@pytest.fixture
def russian():
    """Pin the language for one test and put it back afterwards.

    Requested explicitly rather than made autouse: the detection tests need the
    module's own state left alone. Yields the code so a test can assert against
    it rather than repeating the literal.
    """
    i18n.set_locale("ru")
    yield "ru"
    i18n.set_locale(None)


def test_russian_covers_every_key():
    assert set(RU) == set(EN), {
        "missing_in_ru": sorted(set(EN) - set(RU)),
        "extra_in_ru": sorted(set(RU) - set(EN)),
    }


@pytest.mark.parametrize("code", sorted(CATALOGS))
def test_placeholders_match_english(code: str):
    for key, english in EN.items():
        expected = set(PLACEHOLDER.findall(english))
        actual = set(PLACEHOLDER.findall(CATALOGS[code][key]))
        assert actual == expected, f"{code}[{key}] uses {actual}, English uses {expected}"


def test_translates_and_substitutes(russian: str):
    assert i18n.locale() == russian
    assert i18n._("devices.revoked") == "отозвано"
    assert "5" in i18n._("pair.expires", n=5)


def test_unknown_key_falls_back_to_itself(russian: str):
    assert i18n.locale() == russian
    assert i18n._("no.such.key") == "no.such.key"


def test_missing_translation_falls_back_to_english(russian: str):
    assert i18n.locale() == russian
    try:
        RU.pop("yes")
        assert i18n._("yes") == "yes"
    finally:
        RU["yes"] = "да"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"LANG": "ru_RU.UTF-8"}, "ru"),
        ({"LANG": "ru"}, "ru"),
        ({"LANG": "ru-RU"}, "ru"),
        ({"LANG": "en_GB.UTF-8"}, "en"),
        ({"LANG": "C"}, "en"),
        ({"LANG": "POSIX"}, "en"),
        # A language with no catalogue is not an error, just English.
        ({"LANG": "de_DE.UTF-8"}, "en"),
        ({}, "en"),
        # Empty values are skipped rather than treated as a choice.
        ({"LC_ALL": "", "LANG": "ru_RU.UTF-8"}, "ru"),
        # The explicit override beats the ambient locale.
        ({"WOL_UNLOCK_LANG": "ru", "LANG": "en_US.UTF-8"}, "ru"),
        ({"WOL_UNLOCK_LANG": "en", "LANG": "ru_RU.UTF-8"}, "en"),
        # LC_ALL outranks LANG, as POSIX says.
        ({"LC_ALL": "en_US.UTF-8", "LANG": "ru_RU.UTF-8"}, "en"),
    ],
)
def test_locale_detection(environ: dict[str, str], expected: str):
    assert detect_locale(environ) == expected
