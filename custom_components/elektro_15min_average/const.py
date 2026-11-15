"""Constants of the Elektro 15-minute average integration."""

DOMAIN = "elektro_15min_average"

# Keys in the config entry. Keep them stable.
CONF_SOURCE_ENTITY = "source_entity"
CONF_NAME = "name"
CONF_IMPORT_ONLY = "import_only"

DEFAULT_IMPORT_ONLY = False

STORAGE_VERSION = 1

# Options of the tariff features.
CONF_BLOCK_ENTITY = "block_entity"
# A holiday calendar (on = holiday) or a workday binary sensor (on = working day).
CONF_DAY_ENTITY = "day_entity"
CONF_AGREED_POWER = "agreed_power_{}"  # one per block, in kW
