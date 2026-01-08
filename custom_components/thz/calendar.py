import asyncio
import tzlocal, zoneinfo
from datetime import datetime, time, timedelta
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .register_maps.register_map_manager import RegisterMapManagerWrite
from .thz_device import THZDevice
from .time import quarters_to_time, time_to_quarters


_LOGGER = logging.getLogger(__name__)

# Get local timezone name at import time (sync context)
LOCAL_TIMEZONE_FALLBACK = "UTC"
try:
    local_tz_name = tzlocal.get_localzone_name()
    if local_tz_name is None:
        _LOGGER.warning("tzlocal.get_localzone_name() returned None, falling back to 'UTC'")
        local_tz_name = LOCAL_TIMEZONE_FALLBACK
except Exception as e:
    _LOGGER.error("Failed to get local timezone name: %s, falling back to %s", e, LOCAL_TIMEZONE_FALLBACK)
    local_tz_name = LOCAL_TIMEZONE_FALLBACK
_LOGGER.debug("Local timezone name: %s", local_tz_name)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entities = []
    schedules = []
    write_manager: RegisterMapManagerWrite = hass.data["thz"]["write_manager"]
    device: THZDevice = hass.data["thz"]["device"]
    write_registers = write_manager.get_all_registers()
    _LOGGER.debug("write_registers: %s", write_registers)

    # Use local_tz_name from module scope (already set)
    _LOGGER.debug("Local timezone name: %s", local_tz_name)

    for name, entry in write_registers.items():
        if entry["type"] == "schedule":
            _LOGGER.debug(
                "Creating schedule for %s with command %s", name, entry["command"]
            )

            schedule = THZSchedule(
                name=name,
                command=entry["command"],
                device=device,
                icon=entry.get("icon"),
                unique_id=f"thz_{name.lower().replace(' ', '_')}",
                start_time=None,
                end_time=None,
            )
            schedules.append(schedule)

    # Sort schedules so the first entry ends with '0'
    schedules.sort(key=lambda s: (not s.name.endswith("0"), s.name))

    entity = None
    for schedule in schedules:
        start_time, end_time = await schedule.get_schedule_times_from_device()

        # Skip if device times could not be retrieved
        if start_time is None or end_time is None:
            _LOGGER.warning("Skipping event creation for %s: start_time or end_time is None", schedule.name)
            continue

        # Repeat each event weekly for 52 weeks
        weekly_events = []
        for week in range(52):
            event_start, event_end = calculate_event_times(schedule, start_time, end_time)
            if event_start is None or event_end is None:
                continue
            event_start = (event_start[0] + timedelta(weeks=week), event_start[1])
            event_end = (event_end[0] + timedelta(weeks=week), event_end[1])
            event = {
                "summary": schedule.name,
                "start": event_start,
                "end": event_end,
            }
            weekly_events.append(event)

        if schedule.name.endswith("0"):
            entity = THZCalendar(
                name=schedule.name,
                schedules=weekly_events,
                device=device,
                icon=schedule.icon,
                unique_id=schedule.unique_id,
                local_tz_name=local_tz_name,
            )
            entities.append(entity)
        else:
            if entities:
                entity = entities[-1]
                entity.schedules.extend(weekly_events)
                entities[-1] = entity
            else:
                _LOGGER.warning("No base entity found for schedule %s, skipping.", schedule.name)

    async_add_entities(entities, True)


class THZSchedule:
    def __init__(
        self,
        name: str,
        command: str,
        device: THZDevice,
        start_time: time | None,
        end_time: time | None,
        icon: str | None = None,
        unique_id: str | None = None,
    ) -> None:
        self._name = name
        self._command = command
        self.day_index = self._parse_day_from_name(name)  # e.g., 4 for Friday
        self._device = device
        self._start_time = start_time
        self._end_time = end_time
        self._icon = icon or "mdi:clock"
        self._attr_unique_id = (
            unique_id or f"thz_time_{command.lower()}_{name.lower().replace(' ', '_')}"
        )
        self._attr_native_value = None
        # To get the schedule times, you must await the async function in an async context
        # Example usage in an async method:
        # self._start_time, self._end_time = await self.get_schedule_times_from_device()
        # For __init__, consider initializing with None or fetching times later in an async setup
        self._start_time = None
        self._end_time = None

   
    @property
    def icon(self) -> str:
        """Return the icon for this schedule."""
        return self._icon
    
    @property
    def unique_id(self) -> str | None:
        """Return the unique ID for this schedule."""
        return self._attr_unique_id
    
    @property
    def name(self) -> str:
        """Return the name of the schedule."""
        return self._name

    def _parse_day_from_name(self, name: str) -> int:
        """Extract day index from name (e.g., 'programDHW_Fr_0' -> 4 for Friday)."""
        parts = name.split("_")
        if len(parts) >= 2:
            day_str = parts[1]
            day_map = {
                "Mo": 0,
                "Tu": 1,
                "We": 2,
                "Th": 3,
                "Fr": 4,
                "Sa": 5,
                "So": 6,
                "Mo-Fr": [0, 1, 2, 3, 4],
                "Sa-So": [5, 6],
                "Mo-So": [0, 1, 2, 3, 4, 5, 6],
            }
            return day_map.get(day_str, 0)  # Default to Monday if unknown
        return 0

    async def get_schedule_times_from_device(self) -> tuple[time | None, time | None]:
        """Retrieve schedule times from the device for this entity's day."""
        try:
            async with self._device.lock:
                raw_value = self._device.read_value(
                    bytes.fromhex(self._command), "get", 4, 4
                )
                await asyncio.sleep(
                    0.01
                )  # Kurze Pause, um sicherzustellen, dass das Gerät bereit ist

            _LOGGER.debug("%s: raw_value=%s", self._name, raw_value.hex() if raw_value else raw_value)
            start_time_raw = int.from_bytes(raw_value[0:1], byteorder="little", signed=False)
            end_time_raw = int.from_bytes(raw_value[1:2], byteorder="little", signed=False)
            _LOGGER.debug("%s: start_time_raw=%s, end_time_raw=%s", self._name, start_time_raw, end_time_raw)
            start_time = quarters_to_time(start_time_raw)
            end_time = quarters_to_time(end_time_raw)
            return start_time, end_time
        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.error("Failed to get schedule times for %s: %s", self._name, e)
            return None, None



def calculate_event_times(
    schedule: THZSchedule, start_time: time, end_time: time
) -> tuple[tuple[datetime, str], tuple[datetime, str]]:
    local_tz = tzlocal.get_localzone()
    tz_name = str(local_tz)
    event_start = start_time
    event_end = end_time

    if isinstance(start_time, time) and isinstance(end_time, time):
        today = datetime.now(local_tz).date()
        # Handle day_index as int or list
        day_index = schedule.day_index
        if isinstance(day_index, list):
            # Use the first day in the list for event calculation
            day_index = day_index[0]
        days_ahead = (day_index - today.weekday()) % 7
        event_date = today + timedelta(days=days_ahead)
        event_start = datetime.combine(event_date, start_time)
        event_end = datetime.combine(event_date, end_time)
    # Store tz_name as a string for later reconstruction
    return (event_start, tz_name), (event_end, tz_name)


class THZCalendar(CalendarEntity):
    def __init__(
        self,
        name: str,
        schedules: list[dict],
        device: THZDevice,
        icon: str | None = None,
        unique_id: str | None = None,
        local_tz_name: str | None = None,
    ) -> None:
        """Initialize the THZ Schedule entity.

        Args:
            name: The name of the entity.
            command: The command/register associated with this entity.
            device: The THZDevice instance to interact with.
            icon: Optional icon for the entity.
            unique_id: Optional unique ID for the entity.
        """
        self._attr_name = name
        self._device = device
        self._attr_icon = icon or "mdi:clock"
        self._attr_unique_id = unique_id
        self._attr_native_value = None
        self._schedules = schedules
        self._zoneinfo_cache = {}
        self._local_tz_name = local_tz_name
        # Always populate cache with local_tz_name and 'UTC'
        try:
            if self._local_tz_name and self._local_tz_name not in self._zoneinfo_cache:
                self._zoneinfo_cache[self._local_tz_name] = zoneinfo.ZoneInfo(self._local_tz_name)
        except Exception as e:
            _LOGGER.warning("Could not add local_tz_name '%s' to zoneinfo_cache: %s", self._local_tz_name, e)
        try:
            if 'UTC' not in self._zoneinfo_cache:
                self._zoneinfo_cache['UTC'] = zoneinfo.ZoneInfo('UTC')
        except Exception as e:
            _LOGGER.error("Could not add 'UTC' to zoneinfo_cache: %s", e)

    @property
    def event(self) -> CalendarEvent | None:
        # Return the next event (next occurrence)
        # Use the timezone of the first event, or UTC if none
        tz_name = None
        for sched in self._schedules:
            if sched["start"] is not None and isinstance(sched["start"], tuple):
                tz_name = sched["start"][1]
                break
        if tz_name is None or tz_name == "local":
            tz_name = self._local_tz_name
        
        tzinfo = self._zoneinfo_cache[tz_name]

        now = datetime.now(tzinfo)
        for sched in self._schedules:
            # Find the next occurrence in the future
            base_start = sched["start"][0] if isinstance(sched["start"], tuple) else sched["start"]
            base_end = sched["end"][0] if isinstance(sched["end"], tuple) else sched["end"]
            # Make base_start and base_end timezone-aware if naive
            if base_start.tzinfo is None:
                base_start = base_start.replace(tzinfo=tzinfo)
            if base_end.tzinfo is None:
                base_end = base_end.replace(tzinfo=tzinfo)
            # Calculate how many weeks ahead
            weeks_ahead = ((now - base_start).days // 7) + 1 if now > base_start else 0
            next_start = base_start + timedelta(weeks=weeks_ahead)
            next_end = base_end + timedelta(weeks=weeks_ahead)
            # Attach tzinfo for CalendarEvent (redundant, but safe)
            if next_start.tzinfo is None:
                next_start = next_start.replace(tzinfo=tzinfo)
            if next_end.tzinfo is None:
                next_end = next_end.replace(tzinfo=tzinfo)
            if next_start > now:
                return CalendarEvent(
                    summary=sched["summary"],
                    start=next_start,
                    end=next_end,
                )
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        # Dynamically generate all weekly events in the requested range
        events = []
        for sched in self._schedules:
            base_start = sched["start"]
            base_end = sched["end"]
            # Find the first occurrence in range
            first_week = max(0, ((start_date - base_start).days // 7))
            current_start = base_start + timedelta(weeks=first_week)
            current_end = base_end + timedelta(weeks=first_week)
            while current_start <= end_date:
                if current_end >= start_date:
                    events.append(
                        CalendarEvent(
                            summary=sched["summary"],
                            start=current_start,
                            end=current_end,
                        )
                    )
                current_start += timedelta(weeks=1)
                current_end += timedelta(weeks=1)
        return events
    
    @property
    def schedules(self) -> list[dict]:
        """Return the list of schedules."""
        return self._schedules
