# Fault memory

Firmware 4.x / 5.x. The heat pump keeps its last ten faults but has no
"acknowledged" concept. When the **Fault Log** (`pxxD1`) block is polled,
four sensors are created from it (no extra serial traffic):

| Sensor | Meaning |
|--------|---------|
| Fault status | `No fault` / `Fault` — `Fault` while there are records you have not acknowledged |
| Fault memory | Number of stored records; all records (newest first) are in the `entries` attribute |
| Latest fault | The newest stored fault, translated (`none` if there is none) with code, date and time as attributes |
| New faults | Number of records not yet acknowledged; the records are in the `entries` attribute |

Faults already stored when the integration first sees the block are treated
as acknowledged, so an existing history does not trigger an alarm. The heat
pump stores day and month only, no year.

The **Fault** event entity fires once for every new record; see
[entities.md](entities.md#events) and the notification example in
[automations.md](automations.md).

2.x firmware has a different `pxxD1` layout: no fault memory sensors or
fault events there.

## Services

### `thz.probe_fault_memory`

Read-only. Returns the raw D1 bytes and the decoded records.

### `thz.acknowledge_faults`

Marks all records currently stored as seen. Only affects Home Assistant
(the *Fault status* and *New faults* sensors); nothing is written to the
heat pump.

### `thz.clear_fault_memory`

Physically clears the heat pump's fault memory. It reads and validates D1
first, sends **one** clear command (`0000` to D1, never retried) and
verifies the result by reading D1 again. The history on the device is lost.
You must pass `confirmation: "CLEAR D1"`. It works on every firmware that
provides D1, but the write has only been verified on real hardware on
firmware **4.19**; if the readback still shows faults the service reports an
error.

```yaml
service: thz.clear_fault_memory
data:
  confirmation: "CLEAR D1"
```
