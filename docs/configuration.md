# Configuration and operation

- [Setup and later changes](#setup-and-later-changes)
- [Entity visibility](#entity-visibility)
- [Sub-devices](#sub-devices)
- [How data is updated](#how-data-is-updated)
- [Device clock](#device-clock)

## Setup and later changes

**Settings → Devices & Services → + Add integration → Stiebel Eltron LWZ /
Tecalor THZ**, then choose USB or network (ser2net) and follow the wizard.
It asks for the connection, a device name, the entity ID style, the entity
visibility, HC2 entities, the split into sub-devices, the blocks to poll
with their intervals and the write groups.

- **Reconfigure** (three-dot menu of the entry) changes these settings
  later, including the poll intervals, the firmware override and the
  automatic clock sync.
- **Configure** holds the options of the [controller advisor](advisor.md).

## Entity visibility

To keep the first setup clear, these entities are hidden by default:

- **Time plan/programme entities**: schedule entities (`programDHW_*`,
  `programHC1_*`)
- **Advanced technical parameters**: parameters like gradient, hysteresis,
  integral components (typically p13 and higher)
- **HC2 (Heating Circuit 2) entities**: only needed with a second heating
  circuit, including HC2's own schedule entities (`programHC2_*`)

Two independent settings control this, both asked during setup and
changeable later under **Reconfigure**:

- **Entity visibility**, a tier covering schedules and advanced parameters:
  - *Default*: hide both.
  - *Extended*: enable advanced parameters, keep schedules hidden.
  - *All*: enable both.
- **Enable HC2 entities**, a separate checkbox, off by default. Even the
  *All* tier leaves HC2 hidden until this is checked, since most installs
  have one heating circuit.

Changing either enables or disables the matching entities already in the
registry, not just new ones. An entity you have enabled or disabled by hand
is left alone. Entities can always be enabled one by one via **Settings →
Devices & Services → THZ → device → Show disabled entities**.

## Sub-devices

The entities can be grouped into sub-devices linked to the heat pump:

- Heating circuit 1
- Heating circuit 2
- Hot water
- Ventilation
- Compressor (compressor, refrigerant circuit, defrost, COP)
- Solar
- Cooling

General entities, such as the clock, fault memory, versions, outside
temperature and operating mode, stay on the heat pump device. Each
sub-device has its own device page and can be put in its own area.

**Split into sub-devices** is asked during setup, on by default, and can be
changed under **Reconfigure**. Installations set up before this option
existed keep the single device until you switch it on.

Switching the split on or off keeps the entity IDs, but the displayed names
change. With the split on, a name is made of the sub-device name and the
entity name, for example "lwz Hot water DHW temperature". Automations that
refer to entity IDs keep working. Automations that pick a *device* (device
triggers, conditions or actions) must be pointed to the new device. When the
split is switched off, the entities move back to the heat pump with their
names, areas and enabled state intact, and the sub-devices are removed.

## How data is updated

The integration polls the heat pump over its serial protocol; the heat pump
never pushes anything. Only one request is on the line at a time.

- **Read values** (sensors, binary sensors, climate, water heater): each
  register block has its own coordinator and interval, 600 seconds by
  default, set per block under **Reconfigure**. A block is read in one
  request, and all entities of the block update together.
- **Settings** (number, select, switch, time, fan, and the climate preset
  and cooling setpoint): one parameter poller per heat pump reads every
  setting once per **write interval** (3600 seconds by default), one after
  the other. A register shown by several entities is read once; disabled
  entities are not read. On 2.x firmware, settings inside a polled block
  take their value from that block.
- **After a change from Home Assistant** the entity shows the written value
  at once, and the register (or, for a 2.x setting inside a polled block,
  its block) is read again right away, so every entity showing it follows.
- **Right now:** `homeassistant.update_entity` reads a setting at once;
  `thz.refresh_block` re-reads a block.
- **Clock:** compared with Home Assistant's time every 15 minutes (see
  [Device clock](#device-clock)).

When the heat pump does not answer, the entities become unavailable and
recover with the next successful read.

## Device clock

The heat pump's time programs run on its own clock. Every 15 minutes the
integration compares it with Home Assistant's time. If it is off by more
than a minute:

- with **Auto-sync clock** on (Reconfigure), the clock is corrected;
- otherwise a **repair issue** appears under Settings → System → Repairs.
  Fixing it sets the heat pump clock to Home Assistant's time, and can turn
  on automatic sync for the future. The issue goes away by itself once the
  clock is right again.
