"""Placeholder."""

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("iembot")
    pkgdir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if not pkgdir.endswith("site-packages"):
        __version__ += "-dev"
except PackageNotFoundError:
    # package is not installed
    __version__ = "dev"

DATADIR = Path(__file__).parent / "data"
