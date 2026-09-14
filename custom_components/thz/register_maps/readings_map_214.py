"""Register map for firmware version 214 specific readings.

This module contains REGISTER_MAP definitions specific to firmware version 214.
It extends the base register_map_all definitions with 214-specific sensor mappings.

Ported from the legacy FHEM 00_THZ.pm module's "01pxx214" parsing table (see
docs/legacy/00_THZ.pm) -- pFan (cmd 01) uses a different, shorter byte layout
on 2.14/2.14j than on 2.06 (register_map_206.py's own "pxx01" block, FHEM's
"01pxx206"), so it cannot be shared via readings_map_2xx.py. The blocks common
to all 2xx variants (206/214/214j) live in readings_map_2xx.py instead.

The format follows the standard RegisterMapManager tuple format:
    (name, offset, length, decode_type, factor[, meta_dict])
"""

REGISTER_MAP = {
    "firmware": "214",
    # pFan (cmd 01, FHEM "01pxx214" -- shared by 214 and 214j, distinct from
    # 206's "01pxx206" in register_map_206.py's pxx01 block).
    "pxx01": [
        ("p37Fanstage1AirflowInlet: ", 4, 2, "hex", 1, {"translation_key": "fan_stage1_airflow_inlet"}),
        (" p38Fanstage2AirflowInlet: ", 6, 2, "hex", 1, {"translation_key": "fan_stage2_airflow_inlet"}),
        (" p39Fanstage3AirflowInlet: ", 8, 2, "hex", 1, {"translation_key": "fan_stage3_airflow_inlet"}),
        (" p40Fanstage1AirflowOutlet: ", 10, 2, "hex", 1, {"translation_key": "fan_stage1_airflow_outlet"}),
        (" p41Fanstage2AirflowOutlet: ", 12, 2, "hex", 1, {"translation_key": "fan_stage2_airflow_outlet"}),
        (" p42Fanstage3AirflowOutlet: ", 14, 2, "hex", 1, {"translation_key": "fan_stage3_airflow_outlet"}),
        (" p43UnschedVent3: ", 16, 4, "hex", 1, {"translation_key": "unsched_vent_3"}),
        (" p44UnschedVent2: ", 20, 4, "hex", 1, {"translation_key": "unsched_vent_2"}),
        (" p45UnschedVent1: ", 24, 4, "hex", 1, {"translation_key": "unsched_vent_1"}),
        (" p46UnschedVent0: ", 28, 4, "hex", 1, {"translation_key": "unsched_vent_0"}),
        (" p75PassiveCooling: ", 32, 2, "hex", 1, {"translation_key": "passive_cooling"}),
    ],
}
