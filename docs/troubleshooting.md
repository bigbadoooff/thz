# Troubleshooting

- [USB connection stops working after a host reboot](#usb-connection-stops-working-after-a-host-reboot)
- [No entities are created](#no-entities-are-created)
- [Logging](#logging)
- [Diagnostics](#diagnostics)
- Advisor messages: see [advisor.md](advisor.md#troubleshooting)

When reporting a bug, include the Home Assistant version, the heat pump
model and firmware, the diagnostics download and the relevant log lines
(with debug logging).

## USB connection stops working after a host reboot

If another application (e.g. FHEM) also accesses the serial port, it may
grab the device before Home Assistant on startup, causing "Handshake 1
failed" errors. The heat pump's interface serves one program at a time:
disable the THZ device in FHEM (or whichever application is competing) and
restart Home Assistant.

If Home Assistant runs in Docker and the device was not enumerated when the
container started, restart the container after the USB adapter appears:
`docker restart homeassistant`.

## No entities are created

Check the Home Assistant log for `thz` entries. Common causes:

- Firmware version not detected (empty firmware string) — the integration
  falls back to a default map but some blocks may be empty. A firmware
  override is available under Reconfigure; see [firmware.md](firmware.md).
- Block not supported on the device — blocks returning no data are skipped
  silently.

Use [`thz.read_raw_register`](read-raw-register-service.md) to check that a
block returns data on your device.

## Logging

In normal operation the integration logs one line at startup ("Connected to
the heat pump") and otherwise only what needs attention:

- a lost connection once as a warning, and once as info when it is back
  (the blocks that fail meanwhile are not logged one by one);
- a single setting that cannot be read while the heat pump answers, once
  as a warning, and once as info when it reads again;
- a sensor whose data is too short or cannot be decoded, and an unknown
  select value, once until it reads correctly again;
- a drifted device clock once, when its repair issue is raised (see
  [configuration.md](configuration.md#device-clock)).

For troubleshooting, turn on **Enable debug logging** on the integration's
page, or set the level in `configuration.yaml`, for example:

```yaml
logger:
  logs:
    custom_components.thz: debug              # everything
    custom_components.thz.thz_device: debug   # only the serial/TCP exchange
```

## Diagnostics

1. Go to **Settings** → **Devices & Services** → **THZ**
2. Click on your heat pump device
3. Click **Download Diagnostics**

The report includes firmware version, connection status, coordinator
last-update times, and redacted hex dumps of all currently-polled register
blocks.
