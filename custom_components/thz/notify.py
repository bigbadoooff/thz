"""Persistent notifications raised by the integration."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback


@callback
def async_notify(
    hass: HomeAssistant, *, title: str, message: str, notification_id: str
) -> None:
    """Show (or replace) a persistent notification.

    Calls the persistent_notification helper directly instead of going
    through its "create" service, so it works without depending on the
    service registry.
    """
    persistent_notification.async_create(
        hass, message, title=title, notification_id=notification_id
    )
