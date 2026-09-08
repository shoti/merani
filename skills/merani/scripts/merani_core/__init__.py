"""Internal implementation package for the Merani compatibility launcher.

Modules in this package never import ``merani.py``.  The launcher composes
these modules and retains the public script path and legacy import seams.
"""

from .settings import RuntimePaths

__all__ = ["RuntimePaths"]
