from homeassistant import config_entries

class ThzConfigFlow(config_entries.ConfigFlow, domain="thz"):
    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Validate user input here if needed
            return self.async_create_entry(title="THZ", data=user_input)
        return self.async_show_form(step_id="user", data_schema=None, errors=errors)