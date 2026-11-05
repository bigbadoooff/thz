# Services

All services are under **Developer tools → Actions** with their fields.
With more than one heat pump, most services take the `entry_id` of the one
they act on.

| Service | Does |
|---|---|
| [`thz.refresh_block`](#thzrefresh_block) | Re-reads one register block now |
| [`thz.read_raw_register`](read-raw-register-service.md) | Reads a raw register and returns the hex dump |
| [`thz.scan_raw_registers`](#raw-register-research) | Reads many raw registers by pattern or range |
| [`thz.watch_raw_registers_changes`](#raw-register-research) | Watches raw registers for changes for a while |
| [`thz.set_diverter_valve`](#thzset_diverter_valve) | Moves the 3-way diverter valve by hand |
| [`thz.clear_value`](#thzclear_value) | Clears a time or schedule entity to "unset" |
| [`thz.backup_parameters`](#parameter-backup) | Saves every writable parameter to a file |
| [`thz.restore_parameters`](#parameter-backup) | Writes a saved backup back to the heat pump |
| [`thz.list_parameter_backups`](#parameter-backup) | Lists the saved backups |
| [`thz.probe_fault_memory`](fault-memory.md) | Reads the fault memory |
| [`thz.acknowledge_faults`](fault-memory.md) | Marks the stored faults as seen (Home Assistant only) |
| [`thz.clear_fault_memory`](fault-memory.md) | Clears the heat pump's fault memory |

## `thz.refresh_block`

Forces an immediate re-read of a block without waiting for the next poll
interval. Accepts any block name form (`"FB"`, `"pxxFB"`, `"0xFB"`).
Returns `{success, block}`.

```yaml
service: thz.refresh_block
data:
  block: "FB"
```

## Raw register research

`thz.read_raw_register` reads any raw register block and returns the hex
dump, for firmware research and debugging; it accepts the same block name
forms as `thz.refresh_block`. See
[read-raw-register-service.md](read-raw-register-service.md).

`thz.scan_raw_registers` reads several registers, by a 6-character pattern
with `X` wildcards (`"0A0XXX"` reads 0A0000 to 0A0FFF) or a start/end range,
and returns every register that answers. `thz.watch_raw_registers_changes`
first finds the registers that answer and then watches only those for value
changes for the given time.

## `thz.set_diverter_valve`

Manual control of the 3-way diverter valve motor. Both `heating` and `dhw`
directions are guarded by the `diverterValve` status bit in `pxxF2`, read
from the heat pump right before the move — the command is refused if the
heat pump is currently pressurising the opposite circuit, or if `pxxF2`
cannot be read. After 3 seconds the motor is automatically stopped and the
stop is verified by reading back both motor registers.

```yaml
service: thz.set_diverter_valve
data:
  position: "dhw"   # heating | dhw | off
```

⚠️ Only use this service if you have a manually-controlled 3-way valve and
understand the risk of incorrect actuation.

## `thz.clear_value`

Clears a time or schedule start/end entity back to the device's own "unset"
state, as clearing the slot at the heat pump's menu does. `time.set_value`
cannot do this, since it needs a real time.

## Parameter backup

- `thz.backup_parameters` saves the current value of every writable
  parameter (heating curves, schedules, hot water settings and the other
  number, switch, select and time registers) to a timestamped JSON file in
  `config/thz_backups/`, with an optional `label` in the file name. The
  folder is inside the Home Assistant config directory, so Home Assistant's
  own backups include it.
- `thz.list_parameter_backups` lists the backups, newest first, with their
  creation time and parameter count.
- `thz.restore_parameters` writes a backup back to the heat pump (the newest
  one if no `filename` is given). Each parameter is written with the
  current register map; parameters that no longer exist are skipped and
  reported. `dry_run` shows what would be written without writing, `only`
  restricts it to some parameters. A backup from another firmware is
  refused unless `allow_other_firmware` is on, since parameters of the same
  name can mean something else there.

See [automations.md](automations.md#weekly-parameter-backup) for a weekly
backup.
