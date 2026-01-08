"""Register map definitions for firmware version 214.

This module provides the `REGISTER_MAP` dictionary, which contains mappings for two register groups ("F4" and "FB") used in the THZ integration. Each group is a list of tuples describing register fields, including:

- Field name (str)
- Start position (int)
- Length (int)
- Conversion function or type (str)
- Scaling factor (int or float)

These mappings are used to interpret raw register data from the device.

Structure:
    "F4": [ ... ],
    "FB": [ ... ],
"""

REGISTER_MAP = {
    "firmware": "214",
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
        (" x60: ", 60, 4, "hex2int", 10),
        (" x64: ", 64, 4, "raw", 1),
        (" insideTempRC: ", 68, 4, "hex2int", 10),
        (" x72: ", 72, 4, "raw", 1),
        (" x76: ", 76, 4, "raw", 1),
        (" onHysteresisNo: ", 32, 2, "hex", 1),
        (" offHysteresisNo: ", 34, 2, "hex", 1),
        (" hcBoosterStage: ", 36, 2, "hex", 1),
    ],
    "FB": [
        ("outsideTemp: ", 8, 4, "hex2int", 10),
        (" flowTemp: ", 12, 4, "hex2int", 10),
        (" returnTemp: ", 16, 4, "hex2int", 10),
        (" hotGasTemp: ", 20, 4, "hex2int", 10),
        (" dhwTemp: ", 24, 4, "hex2int", 10),
        (" flowTempHC2: ", 28, 4, "hex2int", 10),
        (" evaporatorTemp: ", 36, 4, "hex2int", 10),
        (" condenserTemp: ", 40, 4, "hex2int", 10),
        (" mixerOpen: ", 47, 1, "bit1", 1),
        (" mixerClosed: ", 47, 1, "bit0", 1),
        (" heatPipeValve: ", 45, 1, "bit3", 1),
        (" diverterValve: ", 45, 1, "bit2", 1),
        (" dhwPump: ", 45, 1, "bit1", 1),
        (" heatingCircuitPump: ", 45, 1, "bit0", 1),
        (" solarPump: ", 44, 1, "bit2", 1),
        (" compressor: ", 44, 1, "bit0", 1),
        (" boosterStage2: ", 44, 1, "bit3", 1),
        (" boosterStage3: ", 44, 1, "n.a.", 1),
        (" boosterStage1: ", 44, 1, "bit1", 1),
        (" highPressureSensor: ", 54, 1, "bit3", 1),
        (" lowPressureSensor: ", 54, 1, "bit2", 1),
        (" evaporatorIceMonitor: ", 55, 1, "bit3", 1),
        (" signalAnode: ", 54, 1, "bit1", 1),
        (" evuRelease: ", 48, 1, "n.a.", 1),
        (" ovenFireplace: ", 54, 1, "bit0", 1),
        (" STB: ", 48, 1, "n.a.", 1),
        (" outputVentilatorPower: ", 48, 2, "hex", 1),
        (" inputVentilatorPower: ", 50, 2, "hex", 1),
        (" mainVentilatorPower: ", 52, 2, "hex", 255 / 100),
        (" outputVentilatorSpeed: ", 56, 2, "hex", 1),
        (" inputVentilatorSpeed: ", 58, 2, "hex", 1),
        (" mainVentilatorSpeed: ", 60, 2, "hex", 1),
        (" outsideTempFiltered: ", 64, 4, "hex2int", 10),
        (" relHumidity: ", 70, 4, "n.a.", 1),
        (" dewPoint: ", 5, 4, "n.a.", 1),
        (" P_Nd: ", 5, 4, "n.a.", 1),
        (" P_Hd: ", 5, 4, "n.a.", 1),
        (" actualPower_Qc: ", 5, 8, "n.a.", 1),
        (" actualPower_Pel: ", 5, 8, "n.a.", 1),
        (" collectorTemp: ", 4, 4, "hex2int", 10),
        (" insideTemp: ", 32, 4, "hex2int", 10),
    ],
}
