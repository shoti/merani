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
        errors, signals = CHECK.check(SCRIPT_DIR / "merani_core")
        self.assertEqual(errors, [])
        self.assertTrue(
            any("merani.py" in item and "run_review_command" in item for item in signals)
        )
        self.assertTrue(
            any("large module" in item and "merani.py" in item for item in signals)
        )


if __name__ == "__main__":
    unittest.main()
