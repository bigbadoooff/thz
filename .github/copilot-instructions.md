# Copilot instructions

Follow [AGENTS.md](../AGENTS.md), [ARCHITECTURE.md](../ARCHITECTURE.md) and
[CONTRIBUTING.md](../CONTRIBUTING.md). In short:

- Read and write write-map parameters only through
  `custom_components/thz/parameter_io.py`.
- Back protocol changes with a reference to FHEM's `docs/legacy/00_THZ.pm`
  or with a golden test on the telegram bytes. FHEM is a protocol reference
  only; the register maps here are newer and are not changed to match it.
- Catch specific exceptions, never a new bare `except Exception`.
- Comments explain the current code, not its history.
- Blocking I/O goes through `THZDevice.async_execute`.
- User-facing strings go in `strings.json` and `translations/`.
- Run ruff (check and format), mypy and both test suites (`tests/`,
  `tests_ha/`) before proposing a change.
