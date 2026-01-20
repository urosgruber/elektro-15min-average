"""Constants for Elektro 15-minute power average."""

DOMAIN = "elektro_15min_average"

CONF_SOURCE_ENTITY = "source_entity"
CONF_METHOD = "average_method"
CONF_NAME = "name"

METHOD_ARITHMETIC = "arithmetic"
METHOD_TIME_WEIGHTED = "time_weighted"
METHODS = [METHOD_ARITHMETIC, METHOD_TIME_WEIGHTED]

DEFAULT_METHOD = METHOD_ARITHMETIC
STORAGE_VERSION = 1
