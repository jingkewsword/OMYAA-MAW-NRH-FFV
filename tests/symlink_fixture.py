import os
import unittest
from pathlib import Path

from scripts.test_policy import SYMLINK_PRIVILEGE_REASON


def create_file_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            raise unittest.SkipTest(SYMLINK_PRIVILEGE_REASON) from error
        raise
