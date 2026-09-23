# Instructions for coding agents

This repository is a Home Assistant custom integration for Stiebel Eltron
LWZ / Tecalor THZ heat pumps, which talk a serial protocol over USB or
ser2net. Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing code and
follow [CONTRIBUTING.md](CONTRIBUTING.md). The rules that matter most:

- **One write path.** Write-map parameters are read and written only through
  `custom_components/thz/parameter_io.py`. 2.x parameters live inside
  blocks, and a plain SET corrupts the block.
- **Protocol changes need proof:**
  - a reference to FHEM's `docs/legacy/00_THZ.pm`, or
  - a golden test on the telegram bytes (`tests/protocol/`).
- **FHEM is a protocol reference only.** Never change register maps to match
  FHEM's tables. The maps here are newer and were confirmed on devices.
- **No new `except Exception`.** Catch specific exceptions.
- **No history in comments.** History belongs in commit messages and issues.
- **Blocking I/O only via `THZDevice.async_execute`.**
- **User-facing strings go in `strings.json` and `translations/`.**

## Checks to run before committing

```bash
ruff check custom_components/thz tests tests_ha
ruff format --check custom_components/thz tests tests_ha
mypy                                   # Python 3.13 with homeassistant-stubs
python3 -m pytest tests/               # stubbed Home Assistant
python3 -m pytest tests_ha -o asyncio_mode=auto   # real Home Assistant, Python 3.13
```

CI requires 95 % coverage for `tests/`. If a register-map change alters the
created entities, the snapshot test in `tests_ha/test_firmware_matrix.py`
fails. Review the diff and accept it with `--snapshot-update`.

Do not edit anything under `docs/legacy/`. It is third-party reference
material.

The project is licensed under GPL v3 and builds on the FHEM module by Immi.
Keep that attribution in the documentation.
