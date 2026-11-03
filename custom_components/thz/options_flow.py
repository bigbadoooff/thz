"""Options flow: the advisor's settings.

The advisor only gives advice; none of these options is written to the
heat pump.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant import config_entries
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .advisor_options import (
    CONF_ADVISOR_FIT_CONTROLLER,
    CONF_ADVISOR_PRICE_ENTITY,
    DEFAULT_FIT_CONTROLLER,
    NUMBER_OPTIONS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ._typing_compat import ConfigFlowResult


def options_schema(options: Mapping[str, Any]) -> vol.Schema:
    """Schema of the advisor options, pre-filled with ``options``."""
    fields: dict[Any, Any] = {}
    for key, spec in NUMBER_OPTIONS.items():
        fields[vol.Required(key, default=options.get(key, spec.default))] = (
            NumberSelector(
                NumberSelectorConfig(
                    min=spec.minimum,
                    max=spec.maximum,
                    step=spec.step,
                    unit_of_measurement=spec.unit,
                    mode=NumberSelectorMode.BOX,
                )
            )
        )
    price_entity = options.get(CONF_ADVISOR_PRICE_ENTITY)
    fields[
        vol.Optional(
            CONF_ADVISOR_PRICE_ENTITY,
            description={"suggested_value": price_entity} if price_entity else None,
        )
    ] = EntitySelector(EntitySelectorConfig(domain="sensor"))
    fields[
        vol.Required(
            CONF_ADVISOR_FIT_CONTROLLER,
            default=options.get(CONF_ADVISOR_FIT_CONTROLLER, DEFAULT_FIT_CONTROLLER),
        )
    ] = BooleanSelector()
    return vol.Schema(fields)


class THZOptionsFlow(config_entries.OptionsFlow):
    """Edit the advisor options of a THZ config entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the advisor options and store them."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=options_schema(self.config_entry.options)
        )
