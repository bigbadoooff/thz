"""Every exception the integration raises to the user is translated."""

import ast
import json
from pathlib import Path
import re
import string

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "thz"
_ERRORS = {"HomeAssistantError", "ServiceValidationError", "ConfigEntryNotReady"}


def _raised_errors():
    """(file, line, keyword args) of each HomeAssistantError-style raise."""
    for path in sorted(COMPONENT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            if isinstance(func, ast.Name) and func.id in _ERRORS:
                where = f"{path.relative_to(COMPONENT)}:{node.lineno}"
                yield where, node.exc


def _exceptions(name):
    path = COMPONENT / name
    return json.loads(path.read_text()).get("exceptions", {})


def _fields(message):
    return {field for _, field, _, _ in string.Formatter().parse(message) if field}


RAISES = list(_raised_errors())
TRANSLATIONS = {
    name: _exceptions(name)
    for name in ("strings.json", "translations/en.json", "translations/de.json")
}


def test_raises_found():
    assert len(RAISES) > 20


@pytest.mark.parametrize(("where", "call"), RAISES, ids=[w for w, _ in RAISES])
def test_raise_is_translated(where, call):
    assert not call.args, f"{where} raises a hard-coded message"
    keywords = {kw.arg: kw.value for kw in call.keywords}
    assert isinstance(keywords.get("translation_key"), ast.Constant), where
    key = keywords["translation_key"].value
    placeholders = keywords.get("translation_placeholders")
    given = (
        {k.value for k in placeholders.keys if isinstance(k, ast.Constant)}
        if isinstance(placeholders, ast.Dict)
        else set()
    )
    for name, exceptions in TRANSLATIONS.items():
        assert key in exceptions, f"{where}: {key} missing in {name}"
        assert _fields(exceptions[key]["message"]) == given, f"{where}: {name}"


def test_translations_have_the_same_keys_and_placeholders():
    strings = TRANSLATIONS["strings.json"]
    for name, exceptions in TRANSLATIONS.items():
        assert exceptions.keys() == strings.keys(), name
        for key, entry in exceptions.items():
            assert _fields(entry["message"]) == _fields(strings[key]["message"]), key


def test_no_placeholder_in_single_quotes():
    """Hassfest rejects placeholders inside single quotes."""
    for name, exceptions in TRANSLATIONS.items():
        for key, entry in exceptions.items():
            assert not re.search(r"'\{\w+\}'", entry["message"]), f"{name}: {key}"


def test_every_translation_is_used():
    used = {
        {kw.arg: kw.value for kw in call.keywords}["translation_key"].value
        for _, call in RAISES
    }
    assert set(TRANSLATIONS["strings.json"]) == used
