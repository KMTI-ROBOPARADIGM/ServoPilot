# -*- coding: utf-8 -*-

"""Top-level package for st3215.

FILE: st3215/__init__.py
PURPOSE: Package initialiser. Re-exports all public names from st3215.py so users
         can write `from st3215 import ST3215` instead of `from st3215.st3215 import ST3215`.
CALLED BY: backend/servo_backend.py `from st3215.st3215 import ST3215`
CONTAINS: Version string, wildcard re-export from st3215.py
"""

__version__ = "0.0.1"

from .st3215 import *

