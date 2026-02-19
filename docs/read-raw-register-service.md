# Using the `thz.read_raw_register` Service

The `thz.read_raw_register` service allows you to read raw register data from your heat pump for debugging purposes. This is particularly useful when:

- Troubleshooting incorrect sensor values on specific firmware versions
- Verifying register byte layouts for firmware compatibility
- Helping developers diagnose issues with your specific hardware/firmware combination

## How to Use

### Via Home Assistant UI

1. Go to **Developer Tools** → **Services**
2. Select the service: `THZ: Read Raw Register`
3. Enter a hex command string in the `command` field
4. Click **Call Service**

The result will appear in:
- The service response (if your HA version supports service responses)
- A persistent notification in your Home Assistant UI
- The Home Assistant log at INFO level

### Via YAML

```yaml
service: thz.read_raw_register
data:
  command: "FB"
```

### Via Automation

```yaml
automation:
  - alias: "Debug heat pump registers"
    trigger:
      - platform: time
        at: "03:00:00"
    action:
      - service: thz.read_raw_register
        data:
          command: "0A0176"
```

## Common Register Commands

| Command | Block Name | Description |
|---------|------------|-------------|
| `FB` | sGlobal | Global status and temperatures |
| `F2` | sControl | Control parameters |
| `0A0176` | sDisplay | Display values (filterDown, service, etc.) |
| `FC` | sTimedate | Time and date information |
| `FD` | sFirmware | Firmware information |
| `FE` | sFirmware-Id | Firmware ID |

## Output Format

The service returns data in three formats:

### 1. Service Response (for automation)
```json
{
  "success": true,
  "command": "FB",
  "length": 45,
  "hex": "010a0705030012...",
  "formatted": "  0000: 01 0a 07 05 03 00 12...\n  0010: ff 00 12 34..."
}
```

### 2. Persistent Notification (for UI users)
A notification appears in Home Assistant with:
- Command sent
- Data length
- Full hex string
- Formatted hex dump with offsets

### 3. Log Entry
The full result is logged at INFO level:
```
INFO Reading raw register: FB
INFO Raw register FB read successfully (45 bytes):
  0000: 01 0a 07 05 03 00 12 34 ff 00 12 34 56 78 9a bc
  0010: de f0 12 34 56 78 9a bc de f0 12 34 56 78 9a
```

## Troubleshooting

### "Invalid hex command" error
- Ensure you're using valid hexadecimal characters (0-9, A-F)
- Don't include spaces or `0x` prefix
- Examples: `FB` ✓, `0A0176` ✓, `0xFB` ✗, `F B` ✗

### "THZ device not initialized" error
- The integration hasn't fully started yet
- Wait a few seconds after restarting Home Assistant
- Check that your heat pump connection is working

### "Communication error"
- Check your USB/network connection
- Verify the register command is supported by your firmware
- Check the Home Assistant logs for more details

## Sharing Data with Developers

When reporting issues related to incorrect sensor values:

1. Run `thz.read_raw_register` with the relevant command
2. Copy the hex output from the notification or logs
3. Include this data in your GitHub issue along with:
   - Your firmware version (from the Device page)
   - Which sensor values are incorrect
   - Expected vs actual values

This helps developers understand how data is structured in your specific firmware version and fix compatibility issues.

## Advanced: Using in Diagnostics

The integration also automatically includes raw block data in the diagnostics download:

1. Go to **Settings** → **Devices & Services** → **THZ**
2. Click on your heat pump device
3. Click **Download Diagnostics**

The diagnostics file includes a `raw_blocks` section with hex dumps of all currently polled registers.
