"""Constants for Elektro 15-minute power average."""

DOMAIN = "elektro_15min_average"
STATIC_URL_PATH = f"/api/{DOMAIN}/static"

# Keys used in config flows and storage; keep stable for backwards compatibility.
CONF_SOURCE_ENTITY = "source_entity"
CONF_METHOD = "average_method"
CONF_NAME = "name"
CONF_FINAL_SENSOR = "create_final_sensor"
CONF_ENTITY_PICTURE = "entity_picture"

METHOD_ARITHMETIC = "arithmetic"
METHOD_TIME_WEIGHTED = "time_weighted"
METHODS = [METHOD_ARITHMETIC, METHOD_TIME_WEIGHTED]

DEFAULT_METHOD = METHOD_ARITHMETIC
DEFAULT_FINAL_SENSOR = False
DEFAULT_ENTITY_PICTURE = f"{STATIC_URL_PATH}/icon.png"
STORAGE_VERSION = 1
