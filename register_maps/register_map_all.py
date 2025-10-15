REGISTER_MAP = {
	"firmware": "all",
	"pxxFB": [
		("outsideTemp: ", 8, 4, "hex2int", 10, 'refreshFB'),
		(" flowTemp: ", 12, 4, "hex2int", 10, 'refreshFB'),
		(" returnTemp: ", 16, 4, "hex2int", 10, 'refreshFB'),
		(" hotGasTemp: ", 20, 4, "hex2int", 10, 'refreshFB'),
		(" dhwTemp: ", 24, 4, "hex2int", 10, 'refreshFB'),
		(" flowTempHC2: ", 28, 4, "hex2int", 10, 'refreshFB'),
		(" evaporatorTemp: ", 36, 4, "hex2int", 10, 'refreshFB'),
		(" condenserTemp: ", 40, 4, "hex2int", 10, 'refreshFB'),
		(" mixerOpen: ", 45, 1, "bit0", 1, 'refreshFB'),
		(" mixerClosed: ", 45, 1, "bit1", 1, 'refreshFB'),
		(" heatPipeValve: ", 45, 1, "bit2", 1, 'refreshFB'),
		(" diverterValve: ", 45, 1, "bit3", 1, 'refreshFB'),
		(" dhwPump: ", 44, 1, "bit0", 1, 'refreshFB'),
		(" heatingCircuitPump: ", 44, 1, "bit1", 1, 'refreshFB'),
		(" solarPump: ", 44, 1, "bit3", 1, 'refreshFB'),
		(" compressor: ", 47, 1, "bit3", 1, 'refreshFB'),
		(" boosterStage3: ", 46, 1, "bit0", 1, 'refreshFB'),
		(" boosterStage2: ", 46, 1, "bit1", 1, 'refreshFB'),
		(" boosterStage1: ", 46, 1, "bit2", 1, 'refreshFB'),
		(" highPressureSensor: ", 49, 1, "nbit0", 1, 'refreshFB'),
		(" lowPressureSensor: ", 49, 1, "nbit1", 1, 'refreshFB'),
		(" evaporatorIceMonitor: ", 49, 1, "bit2", 1, 'refreshFB'),
		(" signalAnode: ", 49, 1, "bit3", 1, 'refreshFB'),
		(" evuRelease: ", 48, 1, "bit0", 1, 'refreshFB'),
		(" ovenFireplace: ", 48, 1, "bit1", 1, 'refreshFB'),
		(" STB: ", 48, 1, "bit2", 1, 'refreshFB'),
		(" outputVentilatorPower: ", 50, 4, "hex", 10, 'refreshFB'),
		(" inputVentilatorPower: ", 54, 4, "hex", 10, 'refreshFB'),
		(" mainVentilatorPower: ", 58, 4, "hex", 10, 'refreshFB'),
		(" outputVentilatorSpeed: ", 62, 4, "hex", 1, 'refreshFB'),
		(" inputVentilatorSpeed: ", 66, 4, "hex", 1, 'refreshFB'),
		(" mainVentilatorSpeed: ", 70, 4, "hex", 1, 'refreshFB'),
		(" outside_tempFiltered: ", 74, 4, "hex2int", 10, 'refreshFB'),
		(" relHumidity: ", 78, 4, "hex2int", 10, 'refreshFB'),
		(" dewPoint: ", 82, 4, "hex2int", 10, 'refreshFB'),
		(" P_Nd: ", 86, 4, "hex2int", 100, 'refreshFB'),
		(" P_Hd: ", 90, 4, "hex2int", 100, 'refreshFB'),
		(" actualPower_Qc: ", 94, 8, "esp_mant", 1, 'refreshFB'),
		(" actualPower_Pel: ", 102, 8, "esp_mant", 1, 'refreshFB'),
		(" collectorTemp: ", 4, 4, "hex2int", 10, 'refreshFB'),
		(" insideTemp: ", 32, 4, "hex2int", 10, 'refreshFB'),
		(" windowOpen: ", 47, 1, "bit2", 1, 'refreshFB'),  # board X18-1 clamp X4-FA (FensterAuf): window open - signal out 230V
		(" quickAirVent: ", 48, 1, "bit3", 1, 'refreshFB'),  # board X15-8 clamp X4-SL (SchnellLüftung): quickAirVent - signal in 230V
		(" flowRate: ", 110, 4, "hex", 100, 'refreshFB'),  # board X51 sensor P5 (on newer models B1 flow temp as well) changed to l/min as suggested by TheTrumpeter Antwort #771
		(" p_HCw: ", 114, 4, "hex", 100, 'refreshFB'),  # board X4-1..3 sensor P4 HC water pressure
		(" humidityAirOut: ", 154, 4, "hex", 100, 'refreshFB')  # board X4-4..6 sensor B15
	],
	"pxxF2": [
		("heatRequest: ", 4, 2, "hex", 1, 'refreshF2'),  # 0=DHW 2=heat 5=off 6=defrostEva
		(" heatRequest2: ", 6, 2, "hex", 1, 'refreshF2'),  # same as heatRequest
		(" hcStage: ", 8, 2, "hex", 1, 'refreshF2'),  # 0=off 1=solar 2=heatPump 3=boost1 4=boost2 5=boost3
		(" dhwStage: ", 10, 2, "hex", 1, 'refreshF2'),  # 0=off, 1=solar, 2=heatPump 3=boostMax
		(" heatStageControlModul: ", 12, 2, "hex", 1, 'refreshF2'),  # either hcStage or dhwStage depending from heatRequest
		(" compBlockTime: ", 14, 4, "hex2int", 1, 'refreshF2'),  # remaining compressor block time
		(" pasteurisationMode: ", 18, 2, "hex", 1, 'refreshF2'),  # 0=off 1=on
		(" defrostEvaporator: ", 20, 2, "raw", 1, 'refreshF2'),  # 10=off 30=defrostEva
		(" boosterStage2: ", 22, 1, "bit3", 1, 'refreshF2'),  # booster 2
		(" solarPump: ", 22, 1, "bit2", 1, 'refreshF2'),  # solar pump
		(" boosterStage1: ", 22, 1, "bit1", 1, 'refreshF2'),  # booster 1
		(" compressor: ", 22, 1, "bit0", 1, 'refreshF2'),  # compressor
		(" heatPipeValve: ", 23, 1, "bit3", 1, 'refreshF2'),  # heat pipe valve
		(" diverterValve: ", 23, 1, "bit2", 1, 'refreshF2'),  # diverter valve
		(" dhwPump: ", 23, 1, "bit1", 1, 'refreshF2'),  # dhw pump
		(" heatingCircuitPump: ", 23, 1, "bit0", 1, 'refreshF2'),  # hc pump
		(" mixerOpen: ", 25, 1, "bit1", 1, 'refreshF2'),  # mixer open
		(" mixerClosed: ", 25, 1, "bit0", 1, 'refreshF2'),  # mixer closed
		(" sensorBits1: ", 26, 2, "raw", 1, 'refreshF2'),  # sensor condenser temperature ??
		(" sensorBits2: ", 28, 2, "raw", 1, 'refreshF2'),  # sensor low pressure ??
		(" boostBlockTimeAfterPumpStart: ", 30, 4, "hex2int", 1, 'refreshF2'),  # after each  pump start (dhw or heat circuit)
		(" boostBlockTimeAfterHD: ", 34, 4, "hex2int", 1, 'refreshF2')  # ??
	],
	"pxxF3": [
		("dhwTemp: ", 4, 4, "hex2int", 10, 'refreshF3'),
		(" outsideTemp: ", 8, 4, "hex2int", 10, 'refreshF3'),
		(" dhwSetTemp: ", 12, 4, "hex2int", 10, 'refreshF3'),
		(" compBlockTime: ", 16, 4, "hex2int", 1, 'refreshF3'),
		(" out: ", 20, 4, "raw", 1, 'refreshF3'),
		(" heatBlockTime: ", 24, 4, "hex2int", 1, 'refreshF3'),
		(" dhwBoosterStage: ", 28, 2, "hex", 1, 'refreshF3'),
		(" pasteurisationMode: ", 32, 2, "hex", 1, 'refreshF3'),
		(" dhwOpMode: ", 34, 2, "opmodehc", 1, 'refreshF3'),
		(" x36: ", 36, 4, "raw", 1, 'refreshF3')
	],
	"pxxF4": [
		("outsideTemp: ", 4, 4, "hex2int", 10, 'refreshF4'),
		(" x08: ", 8, 4, "hex2int", 10, 'refreshF4'),
		(" returnTemp: ", 12, 4, "hex2int", 10, 'refreshF4'),
		(" integralHeat: ", 16, 4, "hex2int", 1, 'refreshF4'),
		(" flowTemp: ", 20, 4, "hex2int", 10, 'refreshF4'),
		(" heatSetTemp: ", 24, 4, "hex2int", 10, 'refreshF4'),
		(" heatTemp: ", 28, 4, "hex2int", 10, 'refreshF4'),
		(" seasonMode: ", 38, 2, "somwinmode", 1, 'refreshF4'),
		# (" x40: ", 40, 4, "hex2int", 1),
		(" integralSwitch: ", 44, 4, "hex2int", 1, 'refreshF4'),
		(" hcOpMode: ", 48, 2, "opmodehc", 1, 'refreshF4'),
		# (" x52: ", 52, 4, "hex2int", 1),
		(" roomSetTemp: ", 56, 4, "hex2int", 10, 'refreshF4'),
		(" x60: ", 60, 4, "hex2int", 10, 'refreshF4'),
		(" x64: ", 64, 4, "hex2int", 10, 'refreshF4'),
		(" insideTempRC: ", 68, 4, "hex2int", 10, 'refreshF4'),
		(" x72: ", 72, 4, "hex2int", 10, 'refreshF4'),
		(" x76: ", 76, 4, "hex2int", 10, 'refreshF4'),
		(" onHysteresisNo: ", 32, 2, "hex", 1, 'refreshF4'),
		(" offHysteresisNo: ", 34, 2, "hex", 1, 'refreshF4'),
		(" hcBoosterStage: ", 36, 2, "hex", 1, 'refreshF4')
	],
    
	"pxxFC" : [
        ("Weekday: ",	5, 1, "weekday", 1, 'refreshFC'),	
        (" Hour: ",	6, 2, "hex", 1, 'refreshFC'),
	      (" Min: ",	8, 2, "hex", 1, 'refreshFC'),	
          (" Sec: ",	10, 2, "hex", 1, 'refreshFC'),
	      (" Date: ", 	12, 2, "year", 1, 'refreshFC'),	
          ("/", 		14, 2, "hex", 1, 'refreshFC'),
	      ("/", 		16, 2, "hex", 1, 'refreshFC')
		],
		    
	"pxxFD" : [("version: ", 	4, 4, "hexdate", 1, 'refreshFD')
	     ],
         
	"pxxFE" : [("HW: ",		30,  2, "hex", 1, 'refreshFE'), 	
            (" SW: ",	32,  4, "swver", 1, 'refreshFE'),
	      (" Date: ",		36, 22, "hex2ascii", 1, 'refreshFE')
	     ],
         
	"pxx0A0176" : [("switchingProg: ",	11, 1, "bit0", 1, 'refresh0A0176'),  
                (" compressor: ",	11, 1, "bit1", 1),
	      (" heatingHC: ",		11, 1, "bit2", 1, 'refresh0A0176'),  (" heatingDHW: ",	10, 1, "bit0", 1, 'refresh0A0176'),
	      (" boosterHC: ",		10, 1, "bit1", 1, 'refresh0A0176'),  (" filterBoth: ",	 9, 1, "bit0", 1, 'refresh0A0176'),
	      (" ventStage: ",		 9, 1, "bit1", 1, 'refresh0A0176'),  (" pumpHC: ",	 9, 1, "bit2", 1, 'refresh0A0176'),
	      (" defrost: ",		 9, 1, "bit3", 1, 'refresh0A0176'),  (" filterUp: ",	 8, 1, "bit0", 1, 'refresh0A0176'),
	      (" filterDown: ",		 8, 1, "bit1", 1, 'refresh0A0176'),  (" cooling: ",	11, 1, "bit3", 1, 'refresh0A0176'),
	      (" service: ",		10, 1, "bit2", 1, 'refresh0A0176')
	      ],
}