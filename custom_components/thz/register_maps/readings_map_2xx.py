"""Register map for the '2xx' firmware series of the THZ component.

This module contains REGISTER_MAP definitions common to all 2xx firmware versions
(206, 214, 214j). It provides sensor definitions that are shared across these
variants, ported from the legacy FHEM 00_THZ.pm module's ``%getsonly2xx`` table
(see docs/legacy/00_THZ.pm) -- every parsing table referenced there under a
"206"-suffixed name (e.g. "09his206", "D1last206" is the exception: FHEM's
``%getsonly206`` requests it only for 206, not 214/214j) is in fact requested
identically for 206, 214, and 214j via the shared ``%getsonly2xx`` dict, so it
belongs here rather than in a firmware-specific file.

Deliberately NOT ported here (FHEM never requests these for 214/214j, only
for 206 -- see ``%getsonly206`` vs ``%getsonly214``/``%getsonly214j``):
    - "D1last206" (sLast10errors, cmd D1): see register_map_206.py's pxxD1.
Firmware-specific blocks (pFan/cmd 01, sHC1/cmd F4, sGlobal/cmd FB) also stay
out of this file since their byte layout differs between 206 and 214/214j.

The format follows the standard RegisterMapManager tuple format:
    (name, offset, length, decode_type, factor[, meta_dict])
"""

_TEMP = {
    "unit": "°C",
    "device_class": "temperature",
    "state_class": "measurement",
    "icon": "mdi:thermometer",
}

REGISTER_MAP = {
    "firmware": "2xx",
    # pDefrostEva (cmd 03, FHEM "03pxx206" -- shared by 206/214/214j).
    "pxx03": [
        ("UpTempLimitDefrostEvaporatorEnd: ", 4, 4, "hex", 10, {"translation_key": "up_temp_limit_defrost_evaporator_end"}),
        (" MaxTimeDefrostEvaporator: ", 8, 4, "hex", 1, {"translation_key": "max_time_defrost_evaporator"}),
        (" LimitTempCondenserElectBoost: ", 12, 4, "hex", 10, {"translation_key": "limit_temp_condenser_elect_boost"}),
        (" LimitTempCondenserDefrostTerm: ", 16, 4, "hex", 10, {"translation_key": "limit_temp_condenser_defrost_term"}),
        (" p47CompressorRestartDelay: ", 20, 2, "hex", 1, {"translation_key": "compressor_restart_delay"}),
        (" p48MainFanSpeed: ", 22, 2, "hex", 1, {"translation_key": "main_fan_speed"}),
    ],
    # pDefrostAA (cmd 04, FHEM "04pxx206").
    "pxx04": [
        ("MaxDefrostDurationAAExchenger: ", 4, 2, "hex", 1, {"translation_key": "max_defrost_duration_aa_exchenger"}),
        (" DefrostStartThreshold: ", 6, 4, "hex", 10, {"translation_key": "defrost_start_threshold"}),
        (" VolumeFlowFilterReplacement: ", 10, 4, "hex", 1, {"translation_key": "volume_flow_filter_replacement"}),
    ],
    # pHeat1 (cmd 05, FHEM "05pxx206").
    "pxx05": [
        ("p13GradientHC1: ", 4, 4, "hex", 10, {"translation_key": "gradient_hc1"}),
        (" p14LowEndHC1: ", 8, 4, "hex", 10, {"translation_key": "low_end_hc1"}),
        (" p15RoomInfluenceHC1: ", 12, 2, "hex", 10, {"translation_key": "room_influence_hc1"}),
        (" p16GradientHC2: ", 14, 4, "hex", 10, {"translation_key": "gradient_hc2"}),
        (" p17LowEndHC2: ", 18, 4, "hex", 10, {"translation_key": "low_end_hc2"}),
        (" p18RoomInfluenceHC2: ", 22, 2, "hex", 10, {"translation_key": "room_influence_hc2"}),
        (" p19FlowProportionHC1: ", 24, 4, "hex", 1, {"translation_key": "flow_proportion_hc1"}),
        (" p20FlowProportionHC2: ", 28, 4, "hex", 1, {"translation_key": "flow_proportion_hc2"}),
        (" MaxSetHeatFlowTempHC1: ", 32, 4, "hex", 10, {"translation_key": "max_set_heat_flow_temp_hc1"}),
        (" MinSetHeatFlowTempHC1: ", 36, 4, "hex", 10, {"translation_key": "min_set_heat_flow_temp_hc1"}),
        (" MaxSetHeatFlowTempHC2: ", 40, 4, "hex", 10, {"translation_key": "max_set_heat_flow_temp_hc2"}),
        (" MinSetHeatFlowTempHC2: ", 44, 4, "hex", 10, {"translation_key": "min_set_heat_flow_temp_hc2"}),
    ],
    # pHeat2 (cmd 06, FHEM "06pxx206").
    "pxx06": [
        ("p21Hyst1: ", 4, 2, "hex", 10, {"translation_key": "hysteresis_1"}),
        (" p22Hyst2: ", 6, 2, "hex", 10, {"translation_key": "hysteresis_2"}),
        (" p23Hyst3: ", 8, 2, "hex", 10, {"translation_key": "hysteresis_3"}),
        (" p24Hyst4: ", 10, 2, "hex", 10, {"translation_key": "hysteresis_4"}),
        (" p25Hyst5: ", 12, 2, "hex", 10, {"translation_key": "hysteresis_5"}),
        (" p26Hyst6: ", 14, 2, "hex", 10, {"translation_key": "hysteresis_6"}),
        (" p27Hyst7: ", 16, 2, "hex", 10, {"translation_key": "hysteresis_7"}),
        (" p28Hyst8: ", 18, 2, "hex", 10, {"translation_key": "hysteresis_8"}),
        (" p29HystAsymmetry: ", 20, 2, "hex", 1, {"translation_key": "hysteresis_asymmetry"}),
        (" p30integralComponent: ", 22, 4, "hex", 1, {"translation_key": "integral_component"}),
        (" p31MaxBoostStages: ", 26, 2, "hex", 1, {"translation_key": "max_boost_stages"}),
        (" MaxHeatFlowTemp: ", 28, 4, "hex", 10, {"translation_key": "max_heat_flow_temp"}),
        (" p49SummerModeTemp: ", 32, 4, "hex", 10, {"translation_key": "summer_mode_temp"}),
        (" p50SummerModeHysteresis: ", 36, 4, "hex", 10, {"translation_key": "summer_mode_hysteresis"}),
        (" p77OutTempFilterTime: ", 40, 4, "hex", 1, {"translation_key": "out_temp_filter_time"}),
        (" p78DualModePoint: ", 44, 4, "hex2int", 10, {**_TEMP, "translation_key": "dual_mode_point"}),
        (" p79BoosterTimeoutHC: ", 48, 2, "hex", 1, {"translation_key": "booster_timeout_hc"}),
    ],
    # pDHW (cmd 07, FHEM "07pxx206").
    "pxx07": [
        ("p32HystDHW: ", 4, 2, "hex", 10, {"translation_key": "hysteresis_dhw"}),
        (" p33BoosterTimeoutDHW: ", 6, 2, "hex", 1, {"translation_key": "booster_timeout_dhw"}),
        (" p34TempLimitBoostDHW: ", 8, 4, "hex2int", 10, {**_TEMP, "translation_key": "temp_limit_boost_dhw"}),
        (" p35PasteurisationInterval: ", 12, 2, "hex", 1, {"translation_key": "pasteurization_interval"}),
        (" p36MaxDurationDHWLoad: ", 14, 2, "hex", 1, {"translation_key": "max_duration_dhw_load"}),
        (" pasteurisationTemp: ", 16, 4, "hex", 10, {"translation_key": "pasteurisation_temp"}),
        (" maxBoostStagesDHW: ", 20, 2, "hex", 1, {"translation_key": "max_boost_stages_dhw"}),
        (" p84EnableDHWBuffer: ", 22, 2, "hex", 1, {"translation_key": "enable_dhw_buffer"}),
    ],
    # pSolar settings (cmd 08, FHEM "08pxx206").
    "pxx08": [
        ("p80EnableSolar: ", 4, 2, "hex", 1, {"translation_key": "enable_solar"}),
        (" p81DiffTempSolarLoading: ", 6, 4, "hex", 10, {"translation_key": "diff_temp_solar_loading"}),
        (" p82DelayCompStartSolar: ", 10, 2, "hex", 1, {"translation_key": "delay_comp_start_solar"}),
        (" p84DHWTempSolarMode: ", 12, 4, "hex", 10, {"translation_key": "dhw_temp_solar_mode"}),
        (" HystDiffTempSolar: ", 16, 4, "hex", 10, {"translation_key": "hyst_diff_temp_solar"}),
        (" CollectLimitTempSolar: ", 20, 4, "hex", 10, {"translation_key": "collect_limit_temp_solar"}),
    ],
    # sHistory (cmd 09, FHEM "09his206" -- operating/heating/DHW/cooling hours).
    "pxx09": [
        ("operatingHours1: ", 4, 4, "hex", 1, {"translation_key": "operating_hours1"}),
        (" operatingHours2: ", 8, 4, "hex", 1, {"translation_key": "operating_hours2"}),
        (" heatingHours: ", 12, 4, "hex", 1, {"translation_key": "heating_hours"}),
        (" DHWhours: ", 16, 4, "hex", 1, {"translation_key": "dhw_hours"}),
        (" coolingHours: ", 20, 4, "hex", 1, {"translation_key": "cooling_hours"}),
    ],
    # pCircPump (cmd 0A, FHEM "0Apxx206").
    "pxx0A": [
        ("p54MinPumpCycles: ", 4, 2, "hex", 1, {"translation_key": "min_pump_cycles"}),
        (" p55MaxPumpCycles: ", 6, 4, "hex", 1, {"translation_key": "max_pump_cycles"}),
        (" p56OutTempMaxPumpCycles: ", 10, 4, "hex", 10, {"translation_key": "out_temp_max_pump_cycles"}),
        (" p57OutTempMinPumpCycles: ", 14, 4, "hex", 10, {"translation_key": "out_temp_min_pump_cycles"}),
        (" p58SuppressTempCaptPumpStart: ", 18, 4, "hex", 1, {"translation_key": "suppress_temp_capt_pump_start"}),
    ],
    # pHeatProg (cmd 0B, FHEM "0Bpxx206").
    "pxx0B": [
        ("progHC1StartTime: ", 4, 4, "hex2time", 1, {"translation_key": "prog_hc1_start_time"}),
        (" progHC1EndTime: ", 8, 4, "hex2time", 1, {"translation_key": "prog_hc1_end_time"}),
        (" progHC1Monday: ", 13, 1, "bit0", 1, {"translation_key": "prog_hc1_monday"}),
        (" progHC1Tuesday: ", 13, 1, "bit1", 1, {"translation_key": "prog_hc1_tuesday"}),
        (" progHC1Wednesday: ", 13, 1, "bit2", 1, {"translation_key": "prog_hc1_wednesday"}),
        (" progHC1Thursday: ", 13, 1, "bit3", 1, {"translation_key": "prog_hc1_thursday"}),
        (" progHC1Friday: ", 12, 1, "bit0", 1, {"translation_key": "prog_hc1_friday"}),
        (" progHC1Saturday: ", 12, 1, "bit1", 1, {"translation_key": "prog_hc1_saturday"}),
        (" progHC1Sunday: ", 12, 1, "bit2", 1, {"translation_key": "prog_hc1_sunday"}),
        (" progHC1Enable: ", 14, 2, "hex", 1, {"translation_key": "prog_hc1_enable"}),
        (" progHC2StartTime: ", 16, 4, "hex2time", 1, {"translation_key": "prog_hc2_start_time"}),
        (" progHC2EndTime: ", 20, 4, "hex2time", 1, {"translation_key": "prog_hc2_end_time"}),
        (" progHC2Monday: ", 25, 1, "bit0", 1, {"translation_key": "prog_hc2_monday"}),
        (" progHC2Tuesday: ", 25, 1, "bit1", 1, {"translation_key": "prog_hc2_tuesday"}),
        (" progHC2Wednesday: ", 25, 1, "bit2", 1, {"translation_key": "prog_hc2_wednesday"}),
        (" progHC2Thursday: ", 25, 1, "bit3", 1, {"translation_key": "prog_hc2_thursday"}),
        (" progHC2Friday: ", 24, 1, "bit0", 1, {"translation_key": "prog_hc2_friday"}),
        (" progHC2Saturday: ", 24, 1, "bit1", 1, {"translation_key": "prog_hc2_saturday"}),
        (" progHC2Sunday: ", 24, 1, "bit2", 1, {"translation_key": "prog_hc2_sunday"}),
        (" progHC2Enable: ", 26, 2, "hex", 1, {"translation_key": "prog_hc2_enable"}),
    ],
    # pDHWProg (cmd 0C, FHEM "0Cpxx206").
    "pxx0C": [
        ("progDHWStartTime: ", 4, 4, "hex2time", 1, {"translation_key": "prog_dhw_start_time"}),
        (" progDHWEndTime: ", 8, 4, "hex2time", 1, {"translation_key": "prog_dhw_end_time"}),
        (" progDHWMonday: ", 13, 1, "bit0", 1, {"translation_key": "prog_dhw_monday"}),
        (" progDHWTuesday: ", 13, 1, "bit1", 1, {"translation_key": "prog_dhw_tuesday"}),
        (" progDHWWednesday: ", 13, 1, "bit2", 1, {"translation_key": "prog_dhw_wednesday"}),
        (" progDHWThursday: ", 13, 1, "bit3", 1, {"translation_key": "prog_dhw_thursday"}),
        (" progDHWFriday: ", 12, 1, "bit0", 1, {"translation_key": "prog_dhw_friday"}),
        (" progDHWSaturday: ", 12, 1, "bit1", 1, {"translation_key": "prog_dhw_saturday"}),
        (" progDHWSunday: ", 12, 1, "bit2", 1, {"translation_key": "prog_dhw_sunday"}),
        (" progDHWEnable: ", 14, 2, "hex", 1, {"translation_key": "prog_dhw_enable"}),
    ],
    # pFanProg (cmd 0D, FHEM "0Dpxx206").
    "pxx0D": [
        ("progFAN1StartTime: ", 4, 4, "hex2time", 1, {"translation_key": "prog_fan1_start_time"}),
        (" progFAN1EndTime: ", 8, 4, "hex2time", 1, {"translation_key": "prog_fan1_end_time"}),
        (" progFAN1Monday: ", 13, 1, "bit0", 1, {"translation_key": "prog_fan1_monday"}),
        (" progFAN1Tuesday: ", 13, 1, "bit1", 1, {"translation_key": "prog_fan1_tuesday"}),
        (" progFAN1Wednesday: ", 13, 1, "bit2", 1, {"translation_key": "prog_fan1_wednesday"}),
        (" progFAN1Thursday: ", 13, 1, "bit3", 1, {"translation_key": "prog_fan1_thursday"}),
        (" progFAN1Friday: ", 12, 1, "bit0", 1, {"translation_key": "prog_fan1_friday"}),
        (" progFAN1Saturday: ", 12, 1, "bit1", 1, {"translation_key": "prog_fan1_saturday"}),
        (" progFAN1Sunday: ", 12, 1, "bit2", 1, {"translation_key": "prog_fan1_sunday"}),
        (" progFAN1Enable: ", 14, 2, "hex", 1, {"translation_key": "prog_fan1_enable"}),
        (" progFAN2StartTime: ", 16, 4, "hex2time", 1, {"translation_key": "prog_fan2_start_time"}),
        (" progFAN2EndTime: ", 20, 4, "hex2time", 1, {"translation_key": "prog_fan2_end_time"}),
        (" progFAN2Monday: ", 25, 1, "bit0", 1, {"translation_key": "prog_fan2_monday"}),
        (" progFAN2Tuesday: ", 25, 1, "bit1", 1, {"translation_key": "prog_fan2_tuesday"}),
        (" progFAN2Wednesday: ", 25, 1, "bit2", 1, {"translation_key": "prog_fan2_wednesday"}),
        (" progFAN2Thursday: ", 25, 1, "bit3", 1, {"translation_key": "prog_fan2_thursday"}),
        (" progFAN2Friday: ", 24, 1, "bit0", 1, {"translation_key": "prog_fan2_friday"}),
        (" progFAN2Saturday: ", 24, 1, "bit1", 1, {"translation_key": "prog_fan2_saturday"}),
        (" progFAN2Sunday: ", 24, 1, "bit2", 1, {"translation_key": "prog_fan2_sunday"}),
        (" progFAN2Enable: ", 26, 2, "hex", 1, {"translation_key": "prog_fan2_enable"}),
    ],
    # pRestart (cmd 0E, FHEM "0Epxx206").
    "pxx0E": [("p59RestartBeforeSetbackEnd: ", 4, 4, "hex", 1, {"translation_key": "restart_before_setback_end"})],
    # pAbsence (cmd 0F, FHEM "0Fpxx206").
    "pxx0F": [
        ("pA0DurationUntilAbsenceStart: ", 4, 4, "hex", 10, {"translation_key": "duration_until_absence_start"}),
        (" pA0AbsenceDuration: ", 8, 4, "hex", 10, {"translation_key": "absence_duration"}),
        (" pA0EnableAbsenceProg: ", 12, 2, "hex", 1, {"translation_key": "enable_absence_prog"}),
    ],
    # pDryHeat (cmd 10, FHEM "10pxx206").
    "pxx10": [
        ("p70StartDryHeat: ", 4, 2, "hex", 1, {"translation_key": "start_dry_heat"}),
        (" p71BaseTemp: ", 6, 4, "hex", 10, {"translation_key": "base_temp"}),
        (" p72PeakTemp: ", 10, 4, "hex", 10, {"translation_key": "peak_temp"}),
        (" p73TempDuration: ", 14, 4, "hex", 1, {"translation_key": "temp_duration"}),
        (" p74TempIncrease: ", 18, 4, "hex", 10, {"translation_key": "temp_increase"}),
    ],
    # sSol -- solar circuit readings (cmd 16, FHEM "16sol"). FHEM's
    # %getsonly2xx requests it identically for 206/214/214j. Same
    # table/offsets as the 4.39/5.39 port in readings_map_439.py's pxx16 block.
    "pxx16": [
        ("collectorTemp: ", 4, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:solar-power", "translation_key": "solar_collector_temp"}),
        (" dhwTemp: ", 8, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:water-boiler", "translation_key": "solar_dhw_temp"}),
        (" flowTemp: ", 12, 4, "hex2int", 10, {**_TEMP, "translation_key": "solar_flow_temp"}),
        (" edSolPump: ", 16, 2, "hex2int", 1, {"icon": "mdi:pump", "translation_key": "solar_pump_hours"}),
        (" out: ", 26, 4, "raw", 1, {"translation_key": "solar_out"}),
        (" status: ", 30, 2, "raw", 1, {"translation_key": "solar_status"}),
    ],
    # p01-p12 (cmd 17, FHEM "17pxx206").
    "pxx17": [
        ("p01RoomTempDay: ", 4, 4, "hex", 10, {"translation_key": "room_temp_day"}),
        (" p02RoomTempNight: ", 8, 4, "hex", 10, {"translation_key": "room_temp_night"}),
        (" p03RoomTempStandby: ", 12, 4, "hex", 10, {"translation_key": "room_temp_standby"}),
        (" p04DHWsetTempDay: ", 16, 4, "hex", 10, {"translation_key": "dhw_temp_day"}),
        (" p05DHWsetTempNight: ", 20, 4, "hex", 10, {"translation_key": "dhw_temp_night"}),
        (" p06DHWsetTempStandby: ", 24, 4, "hex", 10, {"translation_key": "dhw_temp_standby"}),
        (" p07FanStageDay: ", 28, 2, "hex", 1, {"translation_key": "fan_stage_day"}),
        (" p08FanStageNight: ", 30, 2, "hex", 1, {"translation_key": "fan_stage_night"}),
        (" p09FanStageStandby: ", 32, 2, "hex", 1, {"translation_key": "fan_stage_standby"}),
        (" p10HCTempManual: ", 34, 4, "hex", 10, {"translation_key": "hc_temp_manual"}),
        (" p11DHWsetTempManual: ", 38, 4, "hex", 10, {"translation_key": "dhw_temp_manual"}),
        (" p12FanStageManual: ", 42, 2, "hex", 1, {"translation_key": "fan_stage_manual"}),
    ],
    # sFan (cmd E8, FHEM "E8fan206" -- ventilation calibration/actual readings).
    "pxxE8": [
        (
            "statusAFC: ",
            4,
            4,
            "hex",
            1,
            {"translation_key": "status_afc"},
        ),  # 0=init air flow calibration (16:00) 4=normal fan operation
        (" supplyFanSpeedCAL: ", 8, 4, "hex", 60, {"translation_key": "supply_fan_speed_cal"}),  # calibration speed
        (" exhaustFanSpeedCAL: ", 12, 4, "hex", 60, {"translation_key": "exhaust_fan_speed_cal"}),
        (" supplyFanAirflowCAL: ", 16, 4, "hex", 100, {"translation_key": "supply_fan_airflow_cal"}),  # calibration air flow volume
        (" exhaustFanAirflowCAL: ", 20, 4, "hex", 100, {"translation_key": "exhaust_fan_airflow_cal"}),
        (" supplyFanSpeed: ", 24, 4, "hex", 1, {"translation_key": "supply_fan_speed"}),  # actual fan speed in 1/s
        (" exhaustFanSpeed: ", 28, 4, "hex", 1, {"translation_key": "exhaust_fan_speed"}),
        (
            " supplyFanAirflowSet: ",
            32,
            4,
            "hex",
            1,
            {"translation_key": "supply_fan_airflow_set"},
        ),  # actual air flow volume setting in m3/h
        (" exhaustFanAirflowSet: ", 36, 4, "hex", 1, {"translation_key": "exhaust_fan_airflow_set"}),
        (" supplyFanSpeedTarget: ", 40, 4, "hex", 1, {"translation_key": "supply_fan_speed_target"}),  # target fan speed in %
        (" exhaustFanSpeedTarget: ", 44, 4, "hex", 1, {"translation_key": "exhaust_fan_speed_target"}),
        (" supplyFanSpeed0: ", 48, 4, "hex", 10, {"translation_key": "supply_fan_speed0"}),
        (" exhaustFanSpeed0: ", 52, 4, "hex", 10, {"translation_key": "exhaust_fan_speed0"}),
        (" supplyFanSpeed200: ", 56, 4, "hex", 10, {"translation_key": "supply_fan_speed200"}),
        (" exhaustFanSpeed200: ", 60, 4, "hex", 10, {"translation_key": "exhaust_fan_speed200"}),
        (" airflowTolerance: ", 64, 2, "hex", 1, {"translation_key": "airflow_tolerance"}),
        (" airflowCalibrationInterval: ", 66, 2, "hex", 1, {"translation_key": "airflow_calibration_interval"}),  # calibration interval
        (" timeToCalibration: ", 68, 2, "hex", 1, {"translation_key": "time_to_calibration"}),  # days to next calibration
    ],
    # sProgram (cmd EE, FHEM "EEprg206").
    "pxxEE": [
        ("opMode: ", 4, 2, "opmode2", 1, {"translation_key": "op_mode"}),
        (" ProgStateHC: ", 10, 2, "opmodehc", 1, {"translation_key": "prog_state_hc"}),
        (" ProgStateDHW: ", 12, 2, "opmodehc", 1, {"translation_key": "prog_state_dhw"}),
        (" ProgStateFAN: ", 14, 2, "opmodehc", 1, {"translation_key": "prog_state_fan"}),
        (" BaseTimeAP0: ", 16, 8, "hex", 1, {"translation_key": "base_time_ap0"}),
        (" StatusAP0: ", 24, 2, "hex", 1, {"translation_key": "status_ap0"}),
        (" StartTimeAP0: ", 26, 8, "hex", 1, {"translation_key": "start_time_ap0"}),
        (" EndTimeAP0: ", 34, 8, "hex", 1, {"translation_key": "end_time_ap0"}),
    ],
    # sSystem (cmd F6, FHEM "F6sys206").
    "pxxF6": [
        ("userSetFanStage: ", 30, 2, "hex", 1, {"translation_key": "user_set_fan_stage"}),
        (" userSetFanRemainingTime: ", 36, 4, "hex", 1, {"translation_key": "user_set_fan_remaining_time"}),
        (" lastErrors: ", 4, 8, "hex2error", 1, {"translation_key": "last_errors"}),
    ],
    # sTimedate (cmd FC, FHEM "FCtime206").
    "pxxFC": [
        ("Weekday: ", 7, 1, "weekday", 1, {"translation_key": "weekday"}),
        (" pClockHour: ", 8, 2, "hex", 1, {"translation_key": "clock_hour"}),
        (" pClockMinutes: ", 10, 2, "hex", 1, {"translation_key": "clock_minutes"}),
        (" Sec: ", 12, 2, "hex", 1, {"translation_key": "clock_sec"}),
        (" pClockYear: ", 14, 2, "hex", 1, {"translation_key": "clock_year"}),
        (" pClockMonth: ", 18, 2, "hex", 1, {"translation_key": "clock_month"}),
        (" pClockDay: ", 20, 2, "hex", 1, {"translation_key": "clock_day"}),
    ],
}
