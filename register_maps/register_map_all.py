REGISTER_MAP = {
	"firmware": "all",
	"pxxFB": [
		("outsideTemp: ", 8, 4, "hex2int", 10),
		(" flowTemp: ", 12, 4, "hex2int", 10),
		(" returnTemp: ", 16, 4, "hex2int", 10),
		(" hotGasTemp: ", 20, 4, "hex2int", 10),
		(" dhwTemp: ", 24, 4, "hex2int", 10),
		(" flowTempHC2: ", 28, 4, "hex2int", 10),
		(" evaporatorTemp: ", 36, 4, "hex2int", 10),
		(" condenserTemp: ", 40, 4, "hex2int", 10),
		(" mixerOpen: ", 45, 1, "bit0", 1),
		(" mixerClosed: ", 45, 1, "bit1", 1),
		(" heatPipeValve: ", 45, 1, "bit2", 1),
		(" diverterValve: ", 45, 1, "bit3", 1),
		(" dhwPump: ", 44, 1, "bit0", 1),
		(" heatingCircuitPump: ", 44, 1, "bit1", 1),
		(" solarPump: ", 44, 1, "bit3", 1),
		(" compressor: ", 47, 1, "bit3", 1),
		(" boosterStage3: ", 46, 1, "bit0", 1),
		(" boosterStage2: ", 46, 1, "bit1", 1),
		(" boosterStage1: ", 46, 1, "bit2", 1),
		(" highPressureSensor: ", 49, 1, "nbit0", 1),
		(" lowPressureSensor: ", 49, 1, "nbit1", 1),
		(" evaporatorIceMonitor: ", 49, 1, "bit2", 1),
		(" signalAnode: ", 49, 1, "bit3", 1),
		(" evuRelease: ", 48, 1, "bit0", 1),
		(" ovenFireplace: ", 48, 1, "bit1", 1),
		(" STB: ", 48, 1, "bit2", 1),
		(" outputVentilatorPower: ", 50, 4, "hex", 10),
		(" inputVentilatorPower: ", 54, 4, "hex", 10),
		(" mainVentilatorPower: ", 58, 4, "hex", 10),
		(" outputVentilatorSpeed: ", 62, 4, "hex", 1),
		(" inputVentilatorSpeed: ", 66, 4, "hex", 1),
		(" mainVentilatorSpeed: ", 70, 4, "hex", 1),
		(" outside_tempFiltered: ", 74, 4, "hex2int", 10),
		(" relHumidity: ", 78, 4, "hex2int", 10),
		(" dewPoint: ", 82, 4, "hex2int", 10),
		(" P_Nd: ", 86, 4, "hex2int", 100),
		(" P_Hd: ", 90, 4, "hex2int", 100),
		(" actualPower_Qc: ", 94, 8, "esp_mant", 1),
		(" actualPower_Pel: ", 102, 8, "esp_mant", 1),
		(" collectorTemp: ", 4, 4, "hex2int", 10),
		(" insideTemp: ", 32, 4, "hex2int", 10),
		(" windowOpen: ", 47, 1, "bit2", 1),  # board X18-1 clamp X4-FA (FensterAuf): window open - signal out 230V
		(" quickAirVent: ", 48, 1, "bit3", 1),  # board X15-8 clamp X4-SL (SchnellLüftung): quickAirVent - signal in 230V
		(" flowRate: ", 110, 4, "hex", 100),  # board X51 sensor P5 (on newer models B1 flow temp as well) changed to l/min as suggested by TheTrumpeter Antwort #771
		(" p_HCw: ", 114, 4, "hex", 100),  # board X4-1..3 sensor P4 HC water pressure
		(" humidityAirOut: ", 154, 4, "hex", 100)  # board X4-4..6 sensor B15
	],
	"pxxF2": [
		("heatRequest: ", 4, 2, "hex", 1),  # 0=DHW 2=heat 5=off 6=defrostEva
		(" heatRequest2: ", 6, 2, "hex", 1),  # same as heatRequest
		(" hcStage: ", 8, 2, "hex", 1),  # 0=off 1=solar 2=heatPump 3=boost1 4=boost2 5=boost3
		(" dhwStage: ", 10, 2, "hex", 1),  # 0=off, 1=solar, 2=heatPump 3=boostMax
		(" heatStageControlModul: ", 12, 2, "hex", 1),  # either hcStage or dhwStage depending from heatRequest
		(" compBlockTime: ", 14, 4, "hex2int", 1),  # remaining compressor block time
		(" pasteurisationMode: ", 18, 2, "hex", 1),  # 0=off 1=on
		(" defrostEvaporator: ", 20, 2, "raw", 1),  # 10=off 30=defrostEva
		(" boosterStage2: ", 22, 1, "bit3", 1),  # booster 2
		(" solarPump: ", 22, 1, "bit2", 1),  # solar pump
		(" boosterStage1: ", 22, 1, "bit1", 1),  # booster 1
		(" compressor: ", 22, 1, "bit0", 1),  # compressor
		(" heatPipeValve: ", 23, 1, "bit3", 1),  # heat pipe valve
		(" diverterValve: ", 23, 1, "bit2", 1),  # diverter valve
		(" dhwPump: ", 23, 1, "bit1", 1),  # dhw pump
		(" heatingCircuitPump: ", 23, 1, "bit0", 1),  # hc pump
		(" mixerOpen: ", 25, 1, "bit1", 1),  # mixer open
		(" mixerClosed: ", 25, 1, "bit0", 1),  # mixer closed
		(" sensorBits1: ", 26, 2, "raw", 1),  # sensor condenser temperature ??
		(" sensorBits2: ", 28, 2, "raw", 1),  # sensor low pressure ??
		(" boostBlockTimeAfterPumpStart: ", 30, 4, "hex2int", 1),  # after each  pump start (dhw or heat circuit)
		(" boostBlockTimeAfterHD: ", 34, 4, "hex2int", 1)  # ??
	],
	"pxxF3": [
		("dhwTemp: ", 4, 4, "hex2int", 10),
		(" outsideTemp: ", 8, 4, "hex2int", 10),
		(" dhwSetTemp: ", 12, 4, "hex2int", 10),
		(" compBlockTime: ", 16, 4, "hex2int", 1),
		(" out: ", 20, 4, "raw", 1),
		(" heatBlockTime: ", 24, 4, "hex2int", 1),
		(" dhwBoosterStage: ", 28, 2, "hex", 1),
		(" pasteurisationMode: ", 32, 2, "hex", 1),
		(" dhwOpMode: ", 34, 2, "opmodehc", 1),
		(" x36: ", 36, 4, "raw", 1)
	],
	"pxxF4": [
		("outsideTemp: ", 4, 4, "hex2int", 10),
		(" x08: ", 8, 4, "hex2int", 10),
		(" returnTemp: ", 12, 4, "hex2int", 10),
		(" integralHeat: ", 16, 4, "hex2int", 1),
		(" flowTemp: ", 20, 4, "hex2int", 10),
		(" heatSetTemp: ", 24, 4, "hex2int", 10),
		(" heatTemp: ", 28, 4, "hex2int", 10),
		(" seasonMode: ", 38, 2, "somwinmode", 1),
		# (" x40: ", 40, 4, "hex2int", 1),
		(" integralSwitch: ", 44, 4, "hex2int", 1),
		(" hcOpMode: ", 48, 2, "opmodehc", 1),
		# (" x52: ", 52, 4, "hex2int", 1),
		(" roomSetTemp: ", 56, 4, "hex2int", 10),
		(" x60: ", 60, 4, "hex2int", 10),
		(" x64: ", 64, 4, "hex2int", 10),
		(" insideTempRC: ", 68, 4, "hex2int", 10),
		(" x72: ", 72, 4, "hex2int", 10),
		(" x76: ", 76, 4, "hex2int", 10),
		(" onHysteresisNo: ", 32, 2, "hex", 1),
		(" offHysteresisNo: ", 34, 2, "hex", 1),
		(" hcBoosterStage: ", 36, 2, "hex", 1)
	],
    
	"pxxFC" : [
        ("Weekday: ",	5, 1, "weekday", 1),	
        (" Hour: ",	6, 2, "hex", 1),
	      (" Min: ",	8, 2, "hex", 1),	
          (" Sec: ",	10, 2, "hex", 1),
	      (" Date: ", 	12, 2, "year", 1),	
          ("/", 		14, 2, "hex", 1),
	      ("/", 		16, 2, "hex", 1)
		],
		    
	"pxxFD" : [("version: ", 	4, 4, "hexdate", 1)
	     ],
         
	"pxxFE" : [("HW: ",		30,  2, "hex", 1), 	(" SW: ",	32,  4, "swver", 1),
	      (" Date: ",		36, 22, "hex2ascii", 1)
	     ],
         
	"pxx0A0176" : [("switchingProg: ",	11, 1, "bit0", 1),  (" compressor: ",	11, 1, "bit1", 1),
	      (" heatingHC: ",		11, 1, "bit2", 1),  (" heatingDHW: ",	10, 1, "bit0", 1),
	      (" boosterHC: ",		10, 1, "bit1", 1),  (" filterBoth: ",	 9, 1, "bit0", 1),
	      (" ventStage: ",		 9, 1, "bit1", 1),  (" pumpHC: ",	 9, 1, "bit2", 1),
	      (" defrost: ",		 9, 1, "bit3", 1),  (" filterUp: ",	 8, 1, "bit0", 1),
	      (" filterDown: ",		 8, 1, "bit1", 1),  (" cooling: ",	11, 1, "bit3", 1),
	      (" service: ",		10, 1, "bit2", 1)
	      ],
}