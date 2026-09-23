# Tests for THZ Integration

Unit tests for the THZ Home Assistant custom integration. CI runs them (plus
ruff, mypy, hassfest and HACS validation) on every push and pull request, see
`.github/workflows/ci.yml`.

## Running

```bash
pip install -r requirements_test.txt

python3 -m pytest tests/                       # all tests
python3 -m pytest tests/test_parameter_io.py   # one file
python3 -m pytest tests/ --cov=custom_components/thz --cov-report=term-missing

ruff check custom_components/thz tests
```

### Type check

`homeassistant-stubs` uses syntax only Python 3.12+ can parse, so mypy must
run under Python 3.13 (as in CI). Under an older interpreter it only reports
`import-not-found` errors.

```bash
pip install --no-deps homeassistant-stubs
mypy
```

## How the tests are built

- `conftest.py` replaces the Home Assistant modules with lightweight stubs, so
  the suite runs without a Home Assistant installation. Keep stubs faithful
  to the real API (e.g. `async_redact_data` really redacts), otherwise tests
  pass against behaviour Home Assistant does not have.
- Protocol changes need a test against the real telegram format, not only
  against mocked helpers:
  - `test_thz_device.py::TestWriteBlockValue` compares a sent SET telegram
    byte for byte with the FHEM format.
  - `test_parameter_io.py` uses `Simulated2xxDevice`, which keeps 2xx register
    blocks in memory and speaks the real telegram format, to cover the path
    from write-map entry to bytes on the wire.
  - `test_thz_device_coverage.py::TestFrameComplete` covers frame termination
    including escaped `0x10` bytes split across read chunks.
- `test_async_execute.py` runs `THZDevice.async_execute` against a real thread
  pool to cover timeouts, cancellation and lock hand-over.
- Codec changes should keep the round-trip tests in
  `test_value_codec_coverage.py` passing for every step value.
