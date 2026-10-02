"""Compatibility facade for the canonical livestock-tracking module."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("riose.products.livestock_tracking.adapters.persistence.sqlite_store")
