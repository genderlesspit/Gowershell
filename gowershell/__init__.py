import tempfile
from pathlib import Path
import requests
from loguru import logger as log

exe = Path("./gowershell.exe")
# _PERMALINK = r"https://github.com/genderlesspit/Gowershell/blob/3f5382d9dad949941f9c6c55abb8f0c000547d5b/gowershell.exe"
# exe = Path(tempfile.gettempdir()) / "gowershell.exe"
#
# if not exe.exists():
#     pl = _PERMALINK
#     log.warning(f"gowershell.exe not found! Attempting to get from {pl}")
#     r = requests.get(pl)
#     path = Path(tempfile.gettempdir()) / "gowershell.exe"
#     path.write_bytes(r.content)
#
# log.success(f"Found gowershell.exe at {exe}")

from .core import Gowershell, gowershell