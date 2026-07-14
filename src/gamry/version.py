from pathlib import Path
from packaging.version import parse

with Path(__file__).with_name("_version.txt").open("r") as f:
    _version_obj = parse(f.readline().strip())

# Representation of version_info as (x, y, z)
__version__ = str(_version_obj)

__all__ = ("__version__", "_version_obj")
