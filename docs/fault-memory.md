# Fault memory

Firmware 4.x / 5.x. The heat pump keeps its last ten faults but has no
"acknowledged" concept. When the **Fault Log** (`pxxD1`) block is polled,
four sensors are created from it (no extra serial traffic):

| Sensor | Meaning |
|--------|---------|
| Fault status | `No fault` / `Fault` — `Fault` while there are records you have not acknowledged, **or** the heat pump's own service symbol (see below) is lit |
| Fault memory | Number of stored records; all records (newest first) are in the `entries` attribute |
| Latest fault | The newest stored fault, translated (`none` if there is none) with code, date and time as attributes |
| New faults | Number of records not yet acknowledged; the records are in the `entries` attribute |

Faults already stored when the integration first sees the block are treated
as acknowledged, so an existing history does not trigger an alarm. The heat
pump stores day and month only, no year.

### The service symbol

The heat pump's own display lights a service/wrench symbol while a fault is
active (register `0A0176`, bit "service"), and clears it the moment the
owner resets the control unit at the panel. Where that block is polled,
*Fault status* follows it as a second, independent input, alongside D1:

- While the symbol is lit, status stays `Fault` — even right after calling
  `thz.acknowledge_faults` — because that only dismisses the D1 log, not a
  condition the device itself still reports as active.
- Resetting the control unit (the symbol going off) is treated as a
  deliberate acknowledgement: everything currently in D1 is marked seen,
  exactly as `thz.acknowledge_faults` would.
- If the symbol lights again later, status returns to `Fault` immediately,
  **even if D1 never gains a second record** for it — e.g. the same fault
  (say, a float switch) tripping again shows the symbol again without
  necessarily logging a new, distinct D1 entry. The `fault_count`/`entries`
  on *Fault memory* reflect the device's own D1 log either way; only the
  headline status reacts to the symbol between device polls.

Firmware or configurations without the `0A0176` block fall back to the
D1-only behavior above.

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
