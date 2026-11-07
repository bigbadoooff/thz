# How the heating control works

How the heat pump's controller decides when the compressor runs, as far as
it is known from the commissioning manual and from measurements. It applies to the LWZ / THZ 5xx generation; the formulas are
confirmed on an LWZ 5 CS Premium (firmware 7.59). Other models may differ.

The [controller advisor](advisor.md) uses this model to simulate other
settings.

- [In short](#in-short)
- [The formulas](#the-formulas)
- [Settings](#settings)
- [Compressor start and stop](#compressor-start-and-stop)
- [Feed-forward](#feed-forward)
- [Integral component](#integral-component)
- [Practical observations](#practical-observations)
- [What is confirmed and what is open](#what-is-confirmed-and-what-is-open)
- [What follows for the settings](#what-follows-for-the-settings)

## In short

- The controller computes a **relative heating power** (*Heating Relative
  Power*, `sHeatingRelPower`, in %) from the gap between target and actual
  heating-circuit temperature, plus a feed-forward from the outside
  temperature.
- The relative power decides **start and stop** of the compressor: start
  above 40 %, stop below 20 %. It hardly sets the heating power: in mild
  weather the compressor runs at its minimum modulation.
- With the integral component off, it is a **proportional controller with
  hysteresis**. The proportional component KP sets how far the temperature
  swings between start and stop (20 % / KP).

## The formulas

With the integral component switched off (I = 0):

```
T_target  = Rs + LE + G * (Rs - Ta_f) + (RI * G / 10) * (Rs - R_act)
T_control = FS * T_flow + (1 - FS) * T_return
rel       = KP * (T_target - T_control) + P_design * (T_ref - Ta_f) / (T_ref - T_design)
```

- **`T_target`** is the heating curve plus the room influence. The
  integration shows it as *Heat Setpoint Temperature*.
- **`T_control`** is the controlled temperature, a mix of flow and return.
  The integration shows it as *Heat Temperature*.
- **`rel`** is the relative heating power (*Heating Relative Power*).
- **`Ta_f`** is the outside temperature after a first-order filter, with
  the damping as its time constant (*Outside Temperature (Filtered)*).

## Settings

| Symbol | Menu (German display) | Register | Value on the measured device |
|---|---|---|---|
| Rs | Raum-Soll (day / night) | p01 / p02 | 22.5 / 19 °C |
| R_act | Raum-Ist | `insideTempRC` | |
| LE | Fußpunkt | p14 | 3 K |
| G | Steigung (gradient) | p13 | 0.17 |
| RI | Raumeinfluss | p15 | 50 |
| FS | Anteil Vorlauf | p19 / 100 | 0 (return control) |
| KP | P-Anteil | none | 8.5 %/K |
| P_design | Leistung Auslegung Heizen | none | 40 % (range 40–100 %) |
| T_design | Auslegungstemperatur | none | −20 °C (range −25 to +5 °C) |
| T_ref | Bezugstemperatur der Vorsteuerung | fixed | 20 °C |
| τ | Dämpfung Außentemperatur | p77 | 12 h |
| | Integralanteil | p30 / menu | 0 (off) |

KP, P_design and T_design are menu values without a register the
integration can read; enter them in the advisor's options.

## Compressor start and stop

| Condition | Effect |
|---|---|
| rel > 20 % | heating-circuit pump runs continuously |
| rel > 40 % | compressor starts (after the restart lock) |
| rel < 20 % | compressor stops |
| after a stop | 20-minute restart lock |

The band between start and stop is 20 percentage points. In kelvin of
control temperature that is **20 / KP**: about 2.35 K at KP 8.5. A smaller
KP gives longer cycles with a wider temperature swing.

While running, the compressor delivers about its minimum modulation. On the
measured device that is about 2.6 kW (output diagram W35: 2.5–2.9 kW
minimum, 5.5 kW maximum), rising only slightly with the relative power. In
mild weather the house needs less than that minimum, so the heat pump
cycles: it heats at minimum power until rel drops below 20 %, pauses, and
starts again above 40 %.

## Feed-forward

The feed-forward adds a share that depends only on the filtered outside
temperature:

```
FF = P_design * (T_ref - Ta_f) / (T_ref - T_design)
```

It is 0 % at T_ref and P_design at T_design, linear in between. The data
only shows the slope, P_design / (T_ref − T_design): about 1.0 %/K on the
measured device (40 % / (20 − (−20)) K). Design power and design
temperature cannot be told apart from it. Within the allowed ranges
(P_design ≥ 40 %, T_design ≥ −25 °C) a slope of 1.0 %/K leaves only
T_design between −25 and −20 °C with P_design between 40 and 45 %.

## Integral component

The controller is a PID controller. The integral component counters a lasting
gap between target and actual temperature, but it winds up while the
compressor cannot follow: below its minimum modulation the house is
over-supplied, and after a compressor start the integral drives the power
up erratically. On the measured device it is switched off, and the model
assumes I = 0.

Switching it off does not reset the integrator: its last value stays as a
constant offset, and the actual heating-circuit temperature then no longer
falls below the target. After setting it to 0, reset the controller so the
offset goes to zero.

## Practical observations

- **Below the minimum heat load.** In mild weather (roughly 0–10 °C
  outside) the house needs less heat than the compressor's minimum
  modulation. With the integral component on, the PID controller and the
  on/off logic cope badly: after each start the power rises erratically.
  With it off (and the controller reset) the heat pump runs long, even
  cycles at low power.
- **Choosing KP.** The temperature band between start and stop is about
  20 % / KP. Pick KP for the swing the house tolerates, for example 2.5 K
  → KP 8 %/K. The relative power jitters a little, so the effective band is
  somewhat smaller than 20 points; choose KP slightly lower than the
  calculation gives.
- **Flow share.** While the compressor is off, flow and return are about
  equal, so the flow share does not change when it starts. When it runs,
  the flow rises by about 3–4 K; with a flow share of 25 % the controlled
  temperature rises by about 0.9 K, and the relative power drops by
  KP × 0.9 K (about 7 points at KP 8.5). The compressor ramps down sooner
  and runs longer at low power, but also reaches the stop threshold
  sooner. Which effect wins depends on the house.
- **Switching by room setpoint.** The relative power changes by KP × ΔRs
  when the room setpoint changes. An automation can therefore start and
  stop heating with two writes per cycle. It keeps the night setpoint and
  switches to the day setpoint as soon as the computed day relative power
  would exceed 40 %. The advisor does not simulate this switching yet.

## What is confirmed and what is open

Measured on one LWZ 5 CS Premium (firmware 7.59), 10 days of 5-minute data,
outside temperature 4–12 °C:

| Item | Status |
|---|---|
| Heating curve and room influence (`T_target`) | confirmed |
| Proportional component, I = 0 | confirmed: predicted vs measured rel, median error 2.5 points; fitted KP 8.3 %/K against 8.5 set |
| Feed-forward reference temperature | 20 °C, fixed (free fit: 20.3 °C) |
| Feed-forward slope | 1.0 %/K fitted, matching 40 % at −20 °C |
| Thresholds 20 / 40 % | match the data, possibly not exactly |
| Outside temperature filter | first order with τ = p77 (0.03 K RMSE at 12 h) |
| Derivative component | not visible in the data, not modelled |
| Integral component | where it is set (p30 / register 100 or menu) not settled |
| Frost | no data below 2 °C |

The large RMSE of the prediction (8 points) comes from hot water, defrost
and switching transients, where rel drops to −250 %.

## What follows for the settings

- **KP** sets the cycle: the swing between start and stop is 20 / KP K.
- **Heating curve, low end, room influence and feed-forward** set the mean
  temperature level around which the controller cycles.
- Since the compressor runs at minimum power in mild weather, the
  electricity used depends mainly on how warm the house is kept. Lowering
  the room temperature by 1 K saves about 8 % on the measured device; the
  controller settings themselves change the efficiency by 2 % or less at
  the same room temperature.

To try other settings on your own data, use the
[controller advisor](advisor.md): it calibrates this model on your history
and compares settings at equal room temperature.
