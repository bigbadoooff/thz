# Contributing

Thanks for helping! Bug reports and compatibility reports are just as
welcome as code. For a bug, please include:

- the Home Assistant version,
- the heat pump model and firmware version,
- the diagnostics download,
- the relevant log lines (with debug logging for `custom_components.thz`).

[ARCHITECTURE.md](ARCHITECTURE.md) explains how the code is organised.

## Setting up

```bash
pip install -r requirements_test.txt
pip install --no-deps homeassistant-stubs   # for mypy, needs Python 3.13
pip install pre-commit && pre-commit install
```

pre-commit runs ruff (lint and format) and mypy on every commit. CI runs the
same checks plus both test suites, hassfest and HACS validation. See
[tests/README.md](tests/README.md) for running the tests, including the ones
against a real Home Assistant in `tests_ha/`.

## Rules

These keep the protocol code safe to change. Reviews check them.

1. **One write path.** Anything that reads or writes a write-map parameter
   goes through `parameter_io.async_read_parameter` /
   `async_write_parameter`. That covers entities, climate, services and
   clock sync. Never call `device.write_value` or `write_block_value` on a
   write-map entry directly: 2.x parameters live inside blocks, and a plain
   SET overwrites the start of the block.
2. **Protocol changes need proof.** A change to telegrams, escaping,
   checksums, framing or value encoding needs one of:
   - a reference to the matching code in FHEM's `docs/legacy/00_THZ.pm`, or
   - a golden test that compares the bytes on the wire (see
     `tests/protocol/`).

   FHEM is the reference for the protocol only. The register maps here are
   more current than FHEM's tables and are not changed to match them.
3. **No new `except Exception`.** Catch the exceptions that can actually
   occur. For device calls that is `DEVICE_ERRORS` from `exceptions.py`
   (every `THZError` plus unwrapped `OSError`); the device layer raises only
   `THZError` subclasses. ruff's `BLE` rules enforce this. The few existing `# noqa: BLE001` sites are
   deliberate last-resort guards, not a pattern to copy.
4. **No history in comments.** Comments explain why the code is the way it
   is now. How it used to be, which bug led to it, and who changed what
   belong in the commit message and the issue. An issue number is fine when
   it points to details the reader needs.
5. **Register map changes show up in the snapshot.** If a map change adds,
   drops or reclassifies entities, `tests_ha/test_firmware_matrix.py`
   fails. Review the diff and accept it with `--snapshot-update` in the same
   change.
6. **Device access goes through `THZDevice.async_execute`.** It holds the
   device lock and the timeout. The transports are asyncio; nothing may
   block the event loop, and nothing else touches the port or socket.

## Style

- ruff decides formatting and import order. The hand-aligned map files in
  `register_maps/` are excluded from formatting.
- Type hints everywhere. `parameter_io`, `value_codec` and
  `register_map_manager` are checked with mypy's strict flags. Add a module
  to that list in `pyproject.toml` once it passes.
- User-facing text goes through `strings.json` and `translations/`, never a
  hard-coded English string.
- Log with `%s` placeholders, not f-strings:
  - debug for protocol details,
  - info for connection and setup events,
  - warning for recoverable problems.
- New code, comments and docstrings are in English.

## Pull requests

- Keep a pull request to one topic, and reference the issue it addresses.
- Describe what changed for the user. For a protocol or map change, also
  describe how it was verified: a device and firmware, the FHEM reference,
  or a test.
- Update `README.md` for user-visible behaviour and `CHANGELOG.md` for
  anything worth a release note.
