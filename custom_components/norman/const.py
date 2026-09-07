"""Constants for the Norman integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "norman"
MANUFACTURER = "Norman"

# Platforms
PLATFORMS = [Platform.COVER, Platform.SENSOR]

# The hub speaks plain HTTP on a fixed port on the local network; there is no TLS and no
# authentication in the vendor protocol (see docs/NORMAN_API.md).
HUB_PORT = 10123

# Per-request timeout for the short command/status endpoints, in seconds.
REQUEST_TIMEOUT = 10

# Seconds to wait after the notification stream drops before reconnecting.
RECONNECT_INTERVAL = 15
# Max seconds to hold a single notification long-poll open before cycling it. The hub
# silently stops delivering events on very old connections, so they are recycled.
NOTIF_MAX_DURATION = 300

# Bytes read per chunk from the notification stream.
READ_CHUNK_SIZE = 1024
# Upper bound on buffered, not-yet-parsed notification bytes. A hub that never closes a JSON
# object would otherwise grow the buffer without limit.
NOTIF_MAX_BUFFER = 64 * 1024

# Raw hub traffic kept for diagnostics: number of exchanges and max bytes per body.
TRAFFIC_MAX_EXCHANGES = 50
TRAFFIC_BODY_LIMIT = 16 * 1024

# Cover types
COVER_TYPE_SMARTDRAPE = "smartdrape"  # Has position and tilt capabilities

ATTR_TARGET_POSITION = "target_position"
ATTR_TARGET_TILT = "target_tilt"
ATTR_STEP = "step"

SERVICE_NUDGE_POSITION = "nudge_position"
SERVICE_NUDGE_TILT = "nudge_tilt"
SERVICE_GET_HUB_DATA = "get_hub_data"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
