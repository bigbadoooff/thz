"""Re-export decode_raw_value from value_codec for test use.

value_codec has no Home Assistant dependencies so it can be imported
directly in tests (conftest.py mocks all HA modules before import).
"""

from custom_components.thz.value_codec import (
    decode_raw_value as decode_value,  # noqa: F401
)
