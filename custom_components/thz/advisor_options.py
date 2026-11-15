"""Options of the advisor: controller settings without a register, prices.

KP, the design power and the design temperature have no register, so the
user enters them. With ``advisor_fit_controller`` on, the advisor estimates
KP and the feed-forward from the history and uses the entered values only
when the estimate fails.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .advisor.controller import StiebelParams

CONF_ADVISOR_KP = "advisor_kp"
CONF_ADVISOR_DESIGN_POWER = "advisor_design_power"
CONF_ADVISOR_DESIGN_TEMP = "advisor_design_temp"
CONF_ADVISOR_PRICE = "advisor_price"
CONF_ADVISOR_PRICE_ENTITY = "advisor_price_entity"
CONF_ADVISOR_COMFORT_MIN = "advisor_comfort_min"
CONF_ADVISOR_FIT_CONTROLLER = "advisor_fit_controller"
CONF_ADVISOR_POWER_EL_ENTITY = "advisor_power_el_entity"
CONF_ADVISOR_POWER_HEAT_ENTITY = "advisor_power_heat_entity"
CONF_ADVISOR_FLOW_RATE_ENTITY = "advisor_flow_rate_entity"
CONF_ADVISOR_FLOW_RATE = "advisor_flow_rate"

# Optional sensors of other integrations, in the order the form shows them.
ENTITY_OPTIONS = (
    CONF_ADVISOR_PRICE_ENTITY,
    CONF_ADVISOR_POWER_EL_ENTITY,
    CONF_ADVISOR_POWER_HEAT_ENTITY,
    CONF_ADVISOR_FLOW_RATE_ENTITY,
)


@dataclass(frozen=True)
class NumberOption:
    """A numeric option: default, range, step and unit."""

    default: float
    minimum: float
    maximum: float
    step: float
    unit: str


_P = StiebelParams()

# Ranges of the controller settings from the commissioning manual of the
# LWZ 5 CS Premium; defaults are the manual's or the measured installation's.
NUMBER_OPTIONS: Mapping[str, NumberOption] = {
    CONF_ADVISOR_KP: NumberOption(_P.kp, 0.5, 30.0, 0.1, "%/K"),
    CONF_ADVISOR_DESIGN_POWER: NumberOption(_P.design_power, 40.0, 100.0, 1.0, "%"),
    CONF_ADVISOR_DESIGN_TEMP: NumberOption(_P.design_temp, -25.0, 5.0, 1.0, "°C"),
    CONF_ADVISOR_PRICE: NumberOption(0.30, 0.0, 2.0, 0.01, "EUR/kWh"),
    CONF_ADVISOR_COMFORT_MIN: NumberOption(21.0, 15.0, 25.0, 0.5, "°C"),
    # 0: no fixed flow rate.
    CONF_ADVISOR_FLOW_RATE: NumberOption(0.0, 0.0, 5000.0, 10.0, "l/h"),
}
DEFAULT_FIT_CONTROLLER = True


@dataclass(frozen=True)
class AdvisorSettings:
    """The advisor options of one config entry, with defaults filled in."""

    params: StiebelParams
    price_eur_kwh: float
    price_entity: str | None
    comfort_min: float
    fit_controller: bool
    # External sensors in place of the heat pump's own, and a fixed flow
    # rate (l/h) for the heating power from flow x delta T.
    power_el_entity: str | None = None
    power_heat_entity: str | None = None
    flow_rate_entity: str | None = None
    flow_rate_lph: float | None = None


def _number(options: Mapping[str, Any], key: str) -> float:
    spec = NUMBER_OPTIONS[key]
    try:
        value = float(options.get(key, spec.default))
    except (TypeError, ValueError):
        return spec.default
    return min(spec.maximum, max(spec.minimum, value))


def advisor_settings(options: Mapping[str, Any]) -> AdvisorSettings:
    """Read the advisor options; missing or invalid values get defaults."""
    params = _P.with_(
        kp=_number(options, CONF_ADVISOR_KP),
        design_power=_number(options, CONF_ADVISOR_DESIGN_POWER),
        design_temp=_number(options, CONF_ADVISOR_DESIGN_TEMP),
    )
    return AdvisorSettings(
        params=params,
        price_eur_kwh=_number(options, CONF_ADVISOR_PRICE),
        price_entity=options.get(CONF_ADVISOR_PRICE_ENTITY) or None,
        comfort_min=_number(options, CONF_ADVISOR_COMFORT_MIN),
        fit_controller=bool(
            options.get(CONF_ADVISOR_FIT_CONTROLLER, DEFAULT_FIT_CONTROLLER)
        ),
        power_el_entity=options.get(CONF_ADVISOR_POWER_EL_ENTITY) or None,
        power_heat_entity=options.get(CONF_ADVISOR_POWER_HEAT_ENTITY) or None,
        flow_rate_entity=options.get(CONF_ADVISOR_FLOW_RATE_ENTITY) or None,
        flow_rate_lph=_number(options, CONF_ADVISOR_FLOW_RATE) or None,
    )
