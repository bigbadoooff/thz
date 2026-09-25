# Use cases and example automations

The examples use entity IDs as a new installation without an alias creates
them (`THZ 192.0.2.10` becomes `thz_192_0_2_10`). Look up your own IDs under
**Settings → Devices & Services → THZ** and replace them.

## Use cases

- **Monitoring.** Temperatures, operating states, runtime hours and (on
  4.39/5.39) energy values and COP sensors, for the energy dashboard or
  long-term statistics.
- **Fault alerts.** Get a notification as soon as the heat pump stores a new
  fault, instead of noticing it at the control panel days later.
- **Filter reminders.** Get told when the ventilation filters are due.
- **Hot water from surplus power.** Raise the hot water setpoint while a PV
  system exports power, and lower it again afterwards.
- **Ventilation on demand.** Start unscheduled ventilation at a high stage
  when the humidity in the bathroom rises (4.x/5.x).
- **Keeping settings safe.** Back up all parameters before a service visit
  or a firmware update, and restore them afterwards.

## New fault: send a notification

The **Fault** event entity fires once for every record that appears in the
fault memory (firmware 4.x/5.x, `pxxD1` polled).

```yaml
automation:
  - alias: "Heat pump: new fault"
    triggers:
      - trigger: state
        entity_id: event.thz_192_0_2_10_fault
        not_from: unavailable
    conditions:
      - condition: state
        entity_id: event.thz_192_0_2_10_fault
        attribute: event_type
        state: fault
    actions:
      - action: notify.notify
        data:
          title: "Heat pump fault {{ trigger.to_state.attributes.fault_code }}"
          message: >
            {{ trigger.to_state.attributes.description }}
            ({{ trigger.to_state.attributes.date }}
            {{ trigger.to_state.attributes.time }})
```

The fault sensors ("Fault status", "New faults") keep showing unacknowledged
faults until you call `thz.acknowledge_faults`, for example from a dashboard
button.

## Filter change: add a to-do item

The **Filter change** event entity fires when the heat pump starts asking
for a filter change (`pxx0A0176` polled).

```yaml
automation:
  - alias: "Heat pump: filter change due"
    triggers:
      - trigger: state
        entity_id: event.thz_192_0_2_10_filter_change
        not_from: unavailable
    actions:
      - action: todo.add_item
        target:
          entity_id: todo.shopping_list
        data:
          item: >
            Heat pump: {{ state_attr(trigger.entity_id, 'event_type')
            | replace('filter_both', 'change both filters')
            | replace('filter_up', 'change the upper filter')
            | replace('filter_down', 'change the lower filter') }}
```

## Hot water from PV surplus

Raise the hot water setpoint while the grid export is high, lower it again
when it drops. Setting a temperature writes the setpoint that is in effect
(day, or night during setback).

```yaml
automation:
  - alias: "Hot water: use PV surplus"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.grid_export_power
        above: 2000
        for: "00:10:00"
        id: surplus
      - trigger: numeric_state
        entity_id: sensor.grid_export_power
        below: 500
        for: "00:10:00"
        id: normal
    actions:
      - action: water_heater.set_temperature
        target:
          entity_id: water_heater.thz_192_0_2_10_hot_water
        data:
          temperature: "{{ 55 if trigger.id == 'surplus' else 48 }}"
```

## Ventilation boost when the bathroom is humid

On firmware 4.x/5.x the fan starts *unscheduled ventilation*: 100 % runs at
stage 3 for the time set in `p43UnschedVent3`, then the time program takes
over again. Nothing has to be switched back.

```yaml
automation:
  - alias: "Ventilation: boost after a shower"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.bathroom_humidity
        above: 75
    actions:
      - action: fan.set_percentage
        target:
          entity_id: fan.thz_192_0_2_10_ventilation
        data:
          percentage: 100
```

## Weekly parameter backup

`thz.backup_parameters` writes all settings to a JSON file under
`<config>/thz_backups/`; `thz.restore_parameters` writes them back (try it
with `dry_run: true` first). A backup taken on another firmware (for example
before a firmware update) is only restored with `allow_other_firmware: true`,
because a parameter of the same name can have another range there.

```yaml
automation:
  - alias: "Heat pump: weekly backup"
    triggers:
      - trigger: time
        at: "03:30:00"
    conditions:
      - condition: time
        weekday: sun
    actions:
      - action: thz.backup_parameters
        data:
          label: weekly
```

## Show a setting right after changing it at the control panel

Settings are read once per write interval (1 hour by default). To see a
change made at the heat pump's control panel at once, refresh the entity:

```yaml
action: homeassistant.update_entity
target:
  entity_id: number.thz_192_0_2_10_dhw_temperature_day
```

For read-only values, `thz.refresh_block` re-reads a whole block, for
example `block: "FB"`.
