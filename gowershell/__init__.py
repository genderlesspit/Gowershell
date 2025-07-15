from pathlib import Path
from loguru import logger as log
exe: str = Path("./gowershell.exe").exists()



log.debug(f"Found gowershell.exe at {exe}")

from .core import Gowershell, gowershell