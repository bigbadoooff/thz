# Firmware and register maps

- [Supported firmware](#supported-firmware)
- [Confirmed devices](#confirmed-devices)
- [How firmware versions are loaded](#how-firmware-versions-are-loaded)

## Supported firmware

| Firmware | Notes |
|----------|-------|
| 2.06     | Sensor read support; write support via block read-modify-write |
| 2.14 / 2.14j | Sensor read support; write support via block read-modify-write |
| 4.19     | 4.39-like profile for the THZ 303 SOL; a few `pxxFB` sensors the shorter payload cannot supply are disabled. Fault memory clear verified on this firmware |
| 4.39     | Full support including energy sensors, COP, runtime hours, and passive cooling |
| 5.09 / 7.09 | 4.39-based profile with the 5.09 extras (7.09 uses the 5.09 maps) |
| 5.39     | Full support including passive cooling energy sensor (`sCoolHCTotal`) |
| 7.59     | Uses the 5.39 maps |
| Other    | Falls back to a 4.39-like configuration (like the reference FHEM module) — may work partially |

What differs by firmware:

- **2.x:** no fault memory sensors or fault events (different `pxxD1`
  layout), the ventilation can only be shown, not started, and there are no
  energy values, COP, runtime hours by mode or passive cooling.
- **Energy values and COP** need 4.39 or newer.
- **Cooling:** passive cooling exists on 4.39 and 5.39; active cooling only
  on 5.x devices whose cooling hardware answers at setup.
- **Controller advisor:** firmware with the heating relative power (5.39,
  7.x); see [advisor.md](advisor.md).

If auto-detection picks the wrong profile (for example an LWZ 403 reporting
"438"), choose a **firmware override** at setup or under Reconfigure.

## Confirmed devices

| Model | Firmware Version | Status |
|-------|------------------|--------|
| LWZ5  | 7.59 | ✅ Working |

The integration may work with other Stiebel Eltron LWZ and Tecalor THZ
models. Please report which devices work, or do not, in an
[issue](https://github.com/bigbadoooff/thz/issues).

## How firmware versions are loaded

The firmware the heat pump reports at setup (or a firmware override chosen
at setup or under Reconfigure) selects which register map modules the
integration merges together. This determines both which sensors/entities
get created and how their raw bytes are decoded — picking the wrong firmware
typically produces missing entities or garbled values, not errors.

Everything is driven by `RegisterMapManager` / `RegisterMapManagerWrite`
(`custom_components/thz/register_maps/register_map_manager.py`), which build
a merged map for a given `firmware` string in three layers, applied in order
(a later layer's entries win, matched by sensor name within the same
register block):

1. **Base map** — `register_map_all.py` (reads) is always loaded first. It
   defines the registers common to essentially every firmware (climate
   blocks `F2`–`F5`, `sGlobal`/`FB`, `sTimedate`/`FC`, firmware/hardware
   version `FD`/`FE`, etc.), using the 4.39/5.39 byte layout. There is no
   `write_map_all.py` — the base write map is effectively empty.
2. **Write maps** — one or more `write_map_*.py` modules for the firmware,
   merged in listed order.
3. **Read maps** — one or more `readings_map_*.py` / `register_map_*.py`
   modules for the firmware, merged in listed order over the base map.

| `firmware` value | Write maps | Read maps (over the base) |
|---|---|---|
| `206` | `write_map_206` | `readings_map_2xx`, `readings_map_206`, `register_map_206` |
| `214` | `write_map_206`, `write_map_214` | `readings_map_2xx`, `readings_map_214`, `register_map_214` |
| `214j` | `write_map_206`, `write_map_214` | `readings_map_2xx`, `readings_map_214j`, `register_map_214j` |
| `419` | `write_map_439_539`, `write_map_439` | `readings_map_439`, `register_map_419` |
| `439` | `write_map_439_539`, `write_map_439` | `readings_map_439`, `register_map_439` |
| `439technician` | `write_map_439_539`, `write_map_439`, `write_map_X39tech` | `readings_map_439`, `register_map_439` |
| `509` / `709` | `write_map_439_539`, `write_map_539` | `readings_map_439`, `readings_map_509` |
| `539` / `759` | `write_map_439_539`, `write_map_539` | `readings_map_439`, `readings_map_539` |
| `539technician` | `write_map_439_539`, `write_map_539`, `write_map_X39tech` | `readings_map_439`, `readings_map_539` |
| anything else | `write_map_439_539`, `write_map_439` | `readings_map_439` (`default`, treated as 4.39-like) |

`709` is intentionally identical to `509` — the 7.09 firmware has no register
differences from 5.09 that this integration is aware of, and `759` likewise
uses the 5.39 maps. An unrecognized `firmware` string falls back to
`default`, which mirrors the reference FHEM module's own behaviour of
assuming 4.39 rather than guessing at 5.39-like registers that may not exist
on the device (e.g. cooling-only blocks).

### The 2xx family (206 / 214 / 214j)

- `readings_map_2xx.py` holds the sensor blocks the legacy FHEM module
  requests identically for **all three** 2.xx variants (defrost/heating/DHW/
  solar parameters, operating hours, schedules, fan calibration, solar
  circuit, system status, time/date). `readings_map_206.py`,
  `readings_map_214.py`, and `readings_map_214j.py` then only need to add
  what genuinely differs per variant:
  - `pFan` (cmd `01`): 206 uses a longer byte layout than 214/214j, which
    share a shorter one.
  - `sHC1` (cmd `F4`) and `sGlobal` (cmd `FB`): each variant has its own bit
    layout, since the underlying hardware/firmware differ.
  - The fault log `sLast10errors` (cmd `D1`) only exists on 206 — 214/214j
    firmware doesn't expose it, so no entity is created for those variants.
- Writing a parameter on 2xx firmware works differently from 4.39/5.39: the
  protocol has no per-register write command, so `RegisterMapManagerWrite`
  cross-references the read register maps to look up each writable
  parameter's containing block, byte offset, and length, then performs a
  read-modify-write of the whole block (`write_mode="block"`, see
  `_enrich_2xx_write_entries`). 4.39/5.39 write registers directly.
- No energy/COP metering, runtime-hours-by-mode, or passive cooling exists
  on 2xx firmware — those registers were only added starting with 4.39.

### The 4.39 / 5.39 family (439 / 509 / 709 / 539 / 759)

- `readings_map_439.py` is the common base for this family (energy/COP
  sensors, compressor & booster runtime hours, fault log, solar circuit,
  fan speeds); `readings_map_509.py` / `readings_map_539.py` layer
  firmware-specific extras on top (e.g. flow rate, humidity thresholds,
  compressor power/rotation limits, dew point sensors, and — 5.39 only —
  the passive-cooling energy sensor `sCoolHCTotal`).
- Devices without active cooling hardware get cooling-only registers
  stripped from the merged 5.39 maps (`_COOLING_READ_BLOCKS` /
  `_COOLING_WRITE_KEYS`, applied via the `has_cooling` flag from your
  config), so the passive cooling select entity and its related sensors
  only appear when relevant.
- The `439technician` / `539technician` variants add `write_map_X39tech` on
  top of the normal 439/539 write maps, exposing extra technician-only
  parameters that are otherwise not writable.

For the protocol itself see [protocol.md](protocol.md).
