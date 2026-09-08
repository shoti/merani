from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_DIR = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_architecture", SCRIPT_DIR / "check_architecture.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ArchitectureTests(unittest.TestCase):
    def test_internal_dependency_rules(self) -> None:
        errors, _ = CHECK.check(SCRIPT_DIR / "merani_core")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
