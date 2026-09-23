# Tests for THZ Integration

Unit tests for the THZ Home Assistant custom integration. CI runs them (plus
ruff, mypy, hassfest and HACS validation) on every push and pull request, see
`.github/workflows/ci.yml`.

## Running

```bash
pip install -r requirements_test.txt

python3 -m pytest tests/                       # all tests
python3 -m pytest tests/protocol/test_parameter_io.py   # one file
python3 -m pytest tests/ --cov=custom_components/thz --cov-report=term-missing

ruff check custom_components/thz tests tests_ha
ruff format custom_components/thz tests tests_ha
```

`pre-commit install` runs ruff (lint and format) and mypy on every commit;
see `.pre-commit-config.yaml`. The mypy hook uses the mypy of the active
environment, set up as described below.

### Type check

`homeassistant-stubs` uses syntax only Python 3.12+ can parse, so mypy must
run under Python 3.13 (as in CI). Under an older interpreter it only reports
`import-not-found` errors.

```bash
pip install --no-deps homeassistant-stubs
mypy
```

### Tests against a real Home Assistant

`tests_ha/` sets the integration up inside a real Home Assistant instance
(config entries, entity registry, translations, services, diagnostics) with
only the serial/TCP line simulated. It needs Python 3.13 and its own
dependencies, and must be run separately from `tests/`, whose `conftest.py`
replaces Home Assistant with stubs:

```bash
python3.13 -m venv .venv-ha && . .venv-ha/bin/activate
pip install -r requirements_test_ha.txt
python -m pytest tests_ha -o asyncio_mode=auto
```

`tests_ha/test_firmware_matrix.py` sets the integration up once per firmware
and compares the created entities (unique_id, translation key, category,
device class, unit, enabled state) with `tests_ha/snapshots/`. After an
intended register-map change, review the diff and accept it with
`python -m pytest tests_ha -o asyncio_mode=auto --snapshot-update`.

## Layout

Tests are grouped by feature:

| Directory | Covers |
|---|---|
| `protocol/` | THZDevice: telegrams, transport, timeouts, `parameter_io`, FHEM reference, property tests |
| `codec/` | value decoding and encoding |
| `register_maps/` | map selection and merging, firmware-specific map contents |
| `setup/` | config flow, setup/unload, platform setup, visibility tiers, diagnostics |
| `entities/` | sensor, binary sensor, number, select, switch, button, COP, naming, translations |
| `climate/` | climate entities |
| `time_entities/` | time and schedule entities |
| `services/` | `thz.*` services, backup/restore |
| `fault/` | fault memory sensors and services |

Shared test doubles live in `helpers.py`.

## How the tests are built

- `conftest.py` replaces the Home Assistant modules with lightweight stubs, so
  the suite runs without a Home Assistant installation. Keep stubs faithful
  to the real API (e.g. `async_redact_data` really redacts), otherwise tests
  pass against behaviour Home Assistant does not have.
- Protocol changes need a test against the real telegram format, not only
  against mocked helpers:
  - `protocol/test_device.py::TestWriteBlockValue` compares a sent SET telegram
    byte for byte with the FHEM format.
  - `protocol/test_parameter_io.py` uses `Simulated2xxDevice`, which keeps 2xx register
    blocks in memory and speaks the real telegram format, to cover the path
    from write-map entry to bytes on the wire.
  - `protocol/test_transport.py::TestFrameComplete` covers frame termination
    including escaped `0x10` bytes split across read chunks.
- `protocol/test_fhem_reference.py` checks the protocol against FHEM's unmodified
  `docs/legacy/00_THZ.pm`, which is known to work on real devices. The Perl
  harness in `protocol/fhem_reference/` stubs only FHEM's runtime and the serial line,
  and hands FHEM *our* parameter definitions (the register maps here are more
  current than FHEM's tables), so only the protocol is compared: telegram
  framing, checksum, escaping, 2.x read-modify-write and the encoding of each
  value type. Our code and FHEM must produce identical SET telegrams (and, for
  2.x blocks, identical decoded values). Skipped when `perl` is not installed.
- `protocol/test_properties.py` uses hypothesis for invariants that must hold for every
  input: codec round-trips, escaping, frame reading across arbitrary chunk
  boundaries, time quantisation and 2.x block writes touching only their own
  bytes.
- `protocol/test_async_execute.py` runs `THZDevice.async_execute` against a real thread
  pool to cover timeouts, cancellation and lock hand-over.
- Codec changes should keep the round-trip tests in
  `codec/test_value_codec.py` passing for every step value.
