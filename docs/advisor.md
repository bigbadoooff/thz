# Controller advisor

The advisor suggests settings of the heating control that would save
electricity. It models the controller of the Stiebel Eltron LWZ 5 CS
Premium, learns the building and the heat pump from the recorded history,
and simulates candidate settings.

> **Simulation, not measurement.** Every number the advisor shows comes from
> a model. It never writes a setting to the heat pump and never changes the
> operating mode. Change settings yourself, one at a time, and keep a way
> back.

- [What you need](#what-you-need)
- [Entities](#entities)
- [Options](#options)
- [How it works](#how-it-works)
- [Validation](#validation)
- [Limits](#limits)
- [Trying a recommendation](#trying-a-recommendation)
- [Troubleshooting](#troubleshooting)

## What you need

- **Firmware with the heating relative power** (*Heating Relative Power*,
  block `pxx0A069A`): 5.39 and 7.x. Other firmware gets no advisor
  entities.
- **The recorder**, with at least 3 full days of history for the advice
  and some hours for the model check. The advisor reads the last 10 days,
  the recorder's default retention.
- **These sensors enabled and recorded** (found by their translation key,
  whatever their entity ID):

  | Used for | Sensors |
  |---|---|
  | Controller model and self-test | Heating Relative Power, Heat Setpoint Temperature, Heat Temperature, Outside Temperature (Filtered) |
  | Building, compressor and COP | Actual Electric Power, Actual Thermal Power, Return Temperature, Outside Temperature; or external power sensors, or the heating power from flow rate × ΔT (see [Power from other sensors](#power-from-other-sensors)) |

- **Current settings**, read from their number entities: Gradient HC1
  (p13), Low End HC1 (p14), Room Influence HC1 (p15), Flow Proportion HC1
  (p19), outside temperature filter time (p77), room temperature day and
  night HC1. The heating-curve entities are disabled by default; enable
  them, otherwise the advisor assumes the defaults below and lists them in
  the attribute `assumed`.

No data leaves Home Assistant: the advisor reads the recorder and the
current states, nothing else.

## Entities

| Entity | Shows |
|---|---|
| *Advisor: Predicted Relative Power* (%) | What the controller model predicts from the current heat setpoint, heat temperature and filtered outside temperature. Follows those sensors live. |
| *Advisor: Deviation from Relative Power* (%) | Predicted minus measured relative power. |
| *Advisor: Margin to Compressor Stop* (%) | Measured relative power minus the stop threshold (20 %). Attribute `kelvin`: the same in kelvin of control temperature (points / KP). |
| *Advisor: Margin to Compressor Start* (%) | Start threshold (40 %) minus measured relative power, with `kelvin`. |
| *Advisor: Model Error* (%) | Median error of the predicted relative power over the last 10 days. Attributes: settings in use (`kp`, `feed_forward_slope`, `ref_temp`, `design_power`, `design_temp`), their `source` (`fit` or `options`), the self-test (`passed`, `rows`, `rmse`, `bias`), `fit_kp` and `fit_feed_forward_slope`, `fit_rejected`, `missing_inputs`, `error`. |
| *Advisor: Possible Saving* (EUR/day) | Saving of the best candidate against the current settings **at equal room temperature**; 0 if none saves at least 2 %. Attributes: `recommendation` (e.g. `kp 8.5 -> 5`, or `keep the current settings; lowering the room setpoint by 1 K saves about 8 %`), `changes`, `percent_per_k_room`, `ranking` (best five: cost, saving, kWh/day at equal room temperature and as simulated, room change in K, COP, starts/day, room range), `current`, `price_eur_kwh`, `assumed`, `power_sources`, `bound` (set when the result is a [lower bound](#without-electric-power-carnot-estimate)), `runtime_s`, `warnings`, `report`, and `skipped` with the reason when there is no advice. |
| *Advisor: Run Now* (button) | Runs calibration and advice right away. |

The advisor runs after setup, once a day, when its options change and on
the button. A run takes about 2 seconds and runs outside Home Assistant's
event loop.

## Options

**Settings → Devices & services → THZ → Configure.**

| Option | Default | Notes |
|---|---|---|
| Proportional component (KP) | 8.5 %/K | Menu value; no register. |
| Design heating power | 40 % | 40 to 100 %; no register. |
| Design temperature | -20 °C | -25 to +5 °C; no register. |
| Electricity price | 0.30 EUR/kWh | Used when no price sensor is set or it has no value. |
| Electricity price sensor | none | A sensor in EUR/kWh or ct/kWh, e.g. a dynamic tariff. Its current value prices the whole simulation. |
| Comfort limit (room) | 21.0 °C | Time below it counts as a comfort penalty. |
| Estimate KP and feed-forward from the history | on | See [Calibration](#calibration). |
| Electric power sensor (external) | none | A meter used instead of the heat pump's electric power (W or kW). |
| Heating power sensor (external) | none | A heat meter used instead of the heat pump's heating power (W or kW). |
| Flow rate sensor (external) | none | Heating-circuit flow rate (l/h, l/min or m³/h) to compute the heating power. |
| Fixed flow rate | 0 (none) | Flow rate in l/h for that calculation when there is no flow-rate sensor. |

### Power from other sensors

The building identification needs the electric and the heating power. The
advisor takes them from these sources, in this order:

| Value | Sources, first available wins |
|---|---|
| Electric power | external sensor → the heat pump's *Actual Electric Power* → none: [Carnot estimate](#without-electric-power-carnot-estimate) |
| Heating power | external sensor → the heat pump's *Actual Thermal Power* → computed |

Computed heating power: **Q = V̇ × 1.163 Wh/(l·K) × (T_flow − T_return)**,
with the flow rate V̇ from the external flow-rate sensor, else the heat
pump's own *Flow Rate* (5.39 / 7.x), else the fixed flow rate. A fixed
value is an approximation for a pump that runs at constant speed. Use this
for heat pumps without their own power values, or when an energy or heat
meter is more accurate. The attribute `power_sources` of *Advisor:
Possible Saving* shows which sources were used.


### Without electric power: Carnot estimate

Without any electric power value the COP cannot be fitted. The advisor then
uses the **Carnot COP**, the most any heat pump can reach between the flow
temperature (hot side) and the outside air (cold side):

```
COP_max = T_flow / (T_flow - T_outside)      (temperatures in kelvin)
```

A real heat pump reaches only a fraction of it: on the measured device about
0.36 (COP about 5 against a Carnot COP of about 13.5). The electricity
computed with it is therefore far too low, and so are the savings: they are
a **lower bound**, a saving of at least this much.

- *Advisor: Possible Saving* then has the attribute `bound:
  "minimum (Carnot)"`, `power_sources.power_el` reads `Carnot estimate (no
  electric power)`, and a warning says so.
- **kWh and EUR are lower bounds, percentages are not meaningful.** Carnot
  overstates how much the COP depends on the temperature lift, so the
  saving in percent comes out too high. `percent_per_k_room` is left out,
  and the recommendation for the room setpoint is given in kWh/day ("saves
  at least …").
- A candidate is recommended when it saves at least 0.02 EUR/day, instead
  of 2 % of today's cost.
- The bound holds as long as the heat pump's share of the Carnot COP does
  not change much between the settings compared. On the measured data the
  Carnot saving of the best candidate is 0.079 kWh/day against 0.092 kWh/day
  with the fitted COP.
- The heating power is still needed (the heat pump's own, a heat meter or
  flow rate × ΔT): the building and compressor models are identified from
  it.

## How it works

### Controller model

The advisor simulates the heating control of the LWZ 5 CS Premium: heating
curve and room influence give the target temperature, a proportional
controller plus a feed-forward from the outside temperature gives the
relative power, and the relative power starts (above 40 %) and stops (below
20 %) the compressor, which then runs at about its minimum modulation. The
formulas, settings, background and validation are on their own page:
[How the heating control works](heating-control.md).

### Calibration

KP and the feed-forward have no register. With *Estimate KP and
feed-forward from the history* on, the advisor fits them to the recorded
relative power with a robust fit, so hot water, defrost and switching do
not pull it off. Design power and design temperature only enter as their
ratio, the slope P_design / (20 - T_design). The advisor keeps the
configured design temperature and adjusts the design power to the fitted
slope.

The fitted values are used only if the model passes its **self-test** with
them: the median error of the predicted relative power over the heating
rows (relative power above -10 %) must be below 4 percentage points.
Otherwise the entered values are used, and `fit_rejected` says why.

### Advice

Only when the self-test passes, the advisor:

1. identifies the building (heat loss UA from daily means), the compressor
   (minimum power, slope) and the COP (linear in outside temperature,
   return temperature and power) from the last 10 days;
2. simulates the current settings and every combination of KP (3, 5, 8.5),
   room influence (30, 50) and low end (2, 3 K), each over a mild (8 °C
   mean) and a cold (2 °C mean) synthetic week, with the day/night room
   setpoints from the heat pump (22.5 / 19 °C if unknown, day 06-22 h);
3. compares them **at equal room temperature**. A setting that leaves the
   room cooler uses less electricity for that reason alone; the same can
   be had, more directly, from the room setpoint. So the advisor also
   simulates the current settings with the room setpoint 0.5 K lower,
   which gives what one kelvin of mean room temperature costs (about
   8 % of the electricity on the measured data), and corrects every
   candidate's electricity by its change of mean room temperature;
4. ranks them by cost per day: that electricity at the configured price,
   plus 0.05 EUR per compressor start and 0.10 EUR per kelvin-hour below
   the comfort limit;
5. recommends the best only if it saves at least 2 % of today's cost;
   otherwise it recommends keeping the settings and states what a kelvin
   of room temperature saves. The room change of every candidate is in
   the ranking, so a cooler room is visible but not counted as a gain.

## Validation

Measured on one LWZ 5 CS Premium (firmware 7.59), 10 days of 5-minute data,
outside temperature 4 to 12 °C:

| Check | Result |
|---|---|
| Predicted vs measured relative power, entered values | median error 2.5 points, RMSE 8.3, bias -0.9 (RMSE from hot water, defrost and switching) |
| Fitted KP / slope (reference fixed at 20 °C) | 8.3 %/K / 1.03 %/K, against 8.5 / 1.0 set in the menu |
| Free fit of the reference temperature | 20.3 °C |
| Building heat loss UA | 0.06 kW/K |
| COP model | RMSE 0.53 |

## Limits

- **Mild weather only.** The model comes from weeks with outside
  temperatures of 2 °C and above. Advice for frost is extrapolation.
- **Starts per day are not validated.** The simulation does not know the
  day/night switching of automations and shows about one start per day.
  Do not judge cycling by it.
- **Integral and derivative components are not modelled.** The model
  assumes I = 0.
- **One profile.** The controller model is that of the LWZ 5 CS Premium.
  Other models may follow other rules.
- **Synthetic weather.** The candidates are compared over two synthetic
  weeks, not over the forecast.

## Trying a recommendation

1. Note the current value.
2. Change one setting at the heat pump's control panel (or its number
   entity) as recommended.
3. Watch a few days: room temperature, *Advisor: Margin to Compressor
   Stop*, electric energy per day at similar outside temperatures.
4. Keep it or go back.

On the measured data, the controller settings hardly change the
efficiency. Compared at equal room temperature:

| Change | Electricity as simulated | Room (mean) | At equal room temperature |
|---|---|---|---|
| KP 8.5 → 5 | -2.0 % | -0.21 K | -0.3 % |
| KP 5, room influence 30, low end 2 K | -6.9 % | -0.68 K | -1.5 % |
| Design temperature -25 °C | -0.8 % | -0.10 K | 0.0 % |
| KP 3 | -13.6 % | -1.76 K | +0.2 % |

What these settings seem to save comes from a cooler room. Lowering the
room setpoint by 1 K saves about 8 %, with any controller setting.

## Troubleshooting

The reason for a missing value is in the attribute `error` (model error)
or `skipped` (possible saving):

| Message | Meaning |
|---|---|
| `recorder not loaded` | The recorder integration is not running. |
| `no enabled entity: …` | The listed inputs are missing or disabled; enable the sensors. For `power_el` or `power_heat`, set an external sensor or a flow rate under **Configure**. |
| `no recorded values: …` / `the series do not overlap` | Not enough history yet, or the sensors are excluded from the recorder. |
| `model not validated: median error … points (limit 4)` | The model does not describe this heat pump well enough; no advice is given. Check the options (KP, design values) and that the heating ran in the period. |
| `at least 3 full days are needed` | Less than three days of power and temperature history. |
| `too few running rows for the COP` | The compressor hardly ran in the period. |

The advisor's model comes from the `hp_advisor` package (version 0.1). It
is part of this integration under the GPL v3, like the rest of the code,
which builds on the FHEM module by Immi.
