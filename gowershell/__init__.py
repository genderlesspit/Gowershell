from pathlib import Path

from loguru import logger as log

exe = Path("./gowershell.exe")
from .core import Gowershell as _Gowershell, gowershell

Gowershell = _Gowershell()


def set_verbose(bool: bool):  # type: ignore
    Gowershell.verbose = bool
    log.info(f"{Gowershell} verbosity set to {Gowershell.verbose}")
