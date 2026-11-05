# Entities

What the integration creates, beyond the plain sensors, binary sensors and
settings of the register maps. Which entities exist depends on the firmware
and on the blocks selected for polling; see [firmware.md](firmware.md).

- [Platforms](#platforms)
- [Heating, hot water and ventilation](#heating-hot-water-and-ventilation)
- [COP sensors](#cop-sensors)
- [Runtime hours](#runtime-hours)
- [Passive cooling](#passive-cooling)
- [Events](#events)
- [Fault memory](fault-memory.md) and [controller advisor](advisor.md) have
  their own pages.

## Platforms

| Platform | Content |
|---|---|
| Sensor | Temperatures, pressures, operating states, runtime hours, energy, COP |
| Binary sensor | Status flags such as compressor, pumps, valves and filter alarms |
| Switch | Heat pump functions on/off |
| Number | Numeric settings and parameters |
| Select | Predefined options, including the passive cooling mode (4.39/5.39) |
| Time | Time-based parameters, schedules and programmes |
| Button | One-shot commands, e.g. resetting the error list (depending on the firmware); *Advisor: Run Now* |
| Climate | Heating circuits 1 and 2 |
| Water heater | Hot water |
| Fan | Ventilation |
| Event | A new fault, a requested filter change |

Settings that most users do not need are hidden by default; see
[configuration.md](configuration.md#entity-visibility).

## Heating, hot water and ventilation

These entities are created when the required data blocks and parameters are
available:

| Entity | Source | Supports |
|--------|-------------|---------|
| Heating Circuit 1 (climate) | `pxxF4` | Temperature setpoint, HVAC mode (heat, or cool with cooling support: follows the cooling switch, and in cool mode the temperature is the cooling setpoint), preset (operating mode); a circuit in standby shows the action `off` |
| Heating Circuit 2 (climate) | `pxxF5` | Temperature setpoint, HVAC mode, preset — created only when HC2 is configured |
| Hot Water (water heater) | `pxxF3` | Temperature and setpoint in effect; state `performance` (day), `eco` (setback, night setpoint) or `off` (standby). Setting a temperature writes the day setpoint (`p04`), the night setpoint (`p05`) while in eco, or the manual setpoint (`p11`) when that one is in effect. |
| Ventilation (fan) | `p99startUnschedVent` (4.x/5.x), `pxxF6`/`pxxEE` (2.x) | See [Ventilation](#ventilation) |

HC1 also exposes **HVAC action** (heating / cooling / idle / off) and
optional **cooling mode** when the device supports active cooling. The HVAC
mode is what is selected (the cooling switch); the action shows whether the
heat pump is cooling right now.

### Ventilation

The time programs set the ventilation stage; the fan controls *unscheduled
ventilation*. A speed of 33/66/100 % starts it at stage 1/2/3, off starts it
at stage 0, each for the time set in `p43`–`p46`; then the program takes
over again. The program's stage settings (`p07` etc.) are not changed.

Shown is the stage the ventilation runs at, also as the `stage` attribute:
from the supply airflow of the current stage (`pxxE8`, when polled) compared
with `p37`–`p39`, otherwise from today's fan time program (day stage `p07`
inside a window, night stage `p08` outside).

On 2.x firmware, which has no command to start ventilation, the fan only
shows the stage (from the polled blocks `pxxF6` and `pxxEE`): the one set at
the device while its time runs, otherwise the stage of the fan program state
(day, night or standby).

The fan reads its registers through the same parameter poller as the other
settings, so it adds no extra requests for registers that are polled anyway.

## COP sensors

For firmware that provides energy values (4.39 and newer), the integration
provides COP sensors:

- **Current COP**: from the instantaneous heating and electric power
- **Daily COP DHW / Heating / Total**
- **Lifetime COP DHW / Heating / Total**

COP = heat output ÷ electrical input. A COP of 3.0 means 3 kW of heat for
every 1 kW of electricity.

The heat pump resets only the kWh part of its daily energy counters at
midnight and keeps the Wh part. The integration subtracts that kept part, so
the daily counters and the daily COP start at 0 each day. The correction
starts with the first midnight after installation.

## Runtime hours

Firmware 4.39 / 5.39: the `sHistory` block (command `09`) provides
cumulative operating hours for the compressor and booster heaters:

- `compressor_runtime_heating` — compressor hours in heating mode
- `compressor_runtime_cooling` — compressor hours in cooling mode
- `compressor_runtime_dhw` — compressor hours in DHW mode
- `booster_runtime_dhw` — booster heater hours for DHW
- `booster_runtime_heating` — booster heater hours for heating

## Passive cooling

Firmware 4.39 / 5.39: a **Passive Cooling** select entity controls the
passive cooling mode:

| Mode | Description |
|------|-------------|
| `off` | Passive cooling disabled |
| `exhaust_air` | Cool via exhaust air only |
| `supply_air` | Cool via supply air only |
| `bypass` | Bypass mode |
| `sommerkassette` | Summer cassette mode |

## Events

Two event entities let automations react to things that happen once:

| Entity | Event types | Fires when | Attributes |
|--------|-------------|-----------|-----------|
| Fault | `fault` | a new record appears in the fault memory (`pxxD1`, firmware 4.x/5.x) | `fault_number`, `fault_code`, `description`, `time`, `date` |
| Filter change | `filter_both`, `filter_up`, `filter_down` | the heat pump starts asking for that filter change (`pxx0A0176`) | — |

They use data that is polled anyway, so the blocks must be selected for
polling. The fault event remembers the records it has seen, so a fault
stored while Home Assistant was not running fires once after the start. On
the very first start the existing fault history fires nothing, and neither
does a filter that is already due; the fault sensors and filter binary
sensors show that state.

See [automations.md](automations.md) for example automations.
