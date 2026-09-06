"""modpage -- build mod pages from one config, one template, one asset set."""

__version__ = "0.4.2"

#: The config series: ``major.minor``. Only a new series may change what
#: ``modpage.yml`` means; every ``x.y.z`` within a series reads the same config.
SERIES = ".".join(__version__.split(".")[:2])
