from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_DIR = Path(__file__).resolve().parents[2]


class LauncherCompatibilityTests(unittest.TestCase):
    def test_launcher_imports_by_absolute_path(self) -> None:
        path = SCRIPT_DIR / "merani.py"
        spec = importlib.util.spec_from_file_location("merani_compatibility_test", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))
        self.assertEqual(module.SKILL_DIR, SCRIPT_DIR.parent)


if __name__ == "__main__":
    unittest.main()
