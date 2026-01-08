"""Register map definition for firmware version '214j' of the THZ component.

This module contains the REGISTER_MAP dictionary, which specifies the mapping of register names to their respective
offsets, lengths, conversion functions, and scaling factors for the 'F4' register group. Each tuple in the list
represents a register with the following structure:
    (register_name, offset, length, conversion_function, scaling_factor)

Conversion functions include:
    - 'hex2int': Converts hexadecimal to integer.
    - 'raw': Returns raw value.
    - 'somwinmode', 'opmodehc', 'hex', 'bit0', 'bit1', 'bit2', 'bit3': Custom conversion or bit extraction.

This mapping is used for parsing and interpreting data from the THZ device registers.
"""

REGISTER_MAP = {
    "firmware": "214j",
    "F4": [
        ("outsideTemp: ", 4, 4, "hex2int", 10),
        (" x08: ", 8, 4, "raw", 1),
        (" returnTemp: ", 12, 4, "hex2int", 10),
        (" integralHeat: ", 16, 4, "hex2int", 1),
        (" flowTemp: ", 20, 4, "hex2int", 10),
        (" heatSetTemp: ", 24, 4, "hex2int", 10),
        (" heatTemp: ", 28, 4, "hex2int", 10),
        (" seasonMode: ", 38, 2, "somwinmode", 1),
        (" integralSwitch: ", 44, 4, "hex2int", 1),
        (" hcOpMode: ", 48, 2, "opmodehc", 1),
        (" roomSetTemp: ", 62, 4, "hex2int", 10),
        (" x50: ", 50, 4, "hex2int", 10),
        (" x66: ", 66, 4, "raw", 1),
        (" insideTempRC: ", 74, 4, "hex2int", 10),
        (" x70: ", 70, 4, "raw", 1),
        (" x76: ", 78, 4, "raw", 1),
        (" onHysteresisNo: ", 32, 2, "hex", 1),
        (" offHysteresisNo: ", 34, 2, "hex", 1),
        (" hcStage: ", 36, 2, "hex", 1),  # 0=Aus; 1=Solar; 2=V1
        (" boosterStage2: ", 40, 1, "bit3", 1),
        (" x58: ", 58, 4, "raw", 1),
        (" x54: ", 54, 4, "raw", 1),
        (" blockTimeAfterCompStart: ", 82, 4, "hex2int", 1),
        (" insideTemp: ", 86, 4, "hex2int", 10),
        (" solarPump: ", 40, 1, "bit2", 1),
        (" boosterStage1: ", 40, 1, "bit1", 1),
        (" compressor: ", 40, 1, "bit0", 1),
        (" heatPipeValve: ", 41, 1, "bit3", 1),
        (" diverterValve: ", 41, 1, "bit2", 1),
        (" dhwPump: ", 41, 1, "bit1", 1),
        (" heatingCircuitPump: ", 41, 1, "bit0", 1),
        (" mixerOpen: ", 43, 1, "bit1", 1),
        (" mixerClosed: ", 43, 1, "bit0", 1),
    ],
}
