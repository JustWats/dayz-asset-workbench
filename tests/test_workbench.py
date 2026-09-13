"""Boundary and worker failure regression tests; no native DayZ installation needed."""
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from install import safe_extract


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / "workspace/project"
        (self.project / "config").mkdir(parents=True)
        (self.project / "config/toolchain.lock.json").write_text(json.dumps({"blender": {"path": sys.executable},
                                                                          "dayz_tools": str(self.base / "missing-tools")}))
        self.settings = self.base / "settings.json"
        self.settings.write_text(json.dumps({"workspace_root": str(self.project.parent), "default_project": str(self.project),
            "runtime_root": str(self.base / "runtime"), "reference_roots": [], "blender_host": "127.0.0.1", "blender_port": 9876}))
        self.env = patch.dict(os.environ, {"DAYZ_ASSET_SETTINGS": str(self.settings)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.common = importlib.reload(importlib.import_module("common"))
        self.server = importlib.reload(importlib.import_module("server"))

    def test_project_escape(self):
        with self.assertRaises(ValueError):
            self.common.project_path(str(self.base))

    def test_asset_escape(self):
        (self.project.parent / "outside.png").write_bytes(b"test")
        with self.assertRaises(ValueError):
            self.common.read_path("../outside.png", self.project)

    def test_requires_explicit_texture_convention(self):
        (self.project / "basecolor.png").write_bytes(b"test")
        with self.assertRaisesRegex(ValueError, "suffix"):
            self.server.convert_texture("basecolor.png")

    def test_odol_rejected_before_launch(self):
        (self.project / "model.p3d").write_bytes(b"ODOL" + bytes(32))
        with self.assertRaisesRegex(ValueError, "MLOD"):
            self.server.inspect_p3d("model.p3d")

    def test_job_path_escape(self):
        with self.assertRaises(ValueError):
            self.server.get_asset_job("../../config/toolchain.lock")

    def test_export_checks_live_project_before_snapshot(self):
        with patch.object(self.server, "live_project", side_effect=ValueError("other project")):
            with self.assertRaisesRegex(ValueError, "other project"):
                self.server.export_active_p3d()
        self.assertFalse((self.project / "work").exists())

    def test_worker_persists_failure_and_preserves_source(self):
        source = self.project / "fixture_co.png"
        source.write_bytes(b"source stays unchanged")
        folder = self.server.new_job(self.project, "texture", {"source": str(source), "format": "paa", "suffix": "preserve"})
        result = subprocess.run([sys.executable, str(ROOT / "scripts/job_runner.py"), str(folder / "request.json")],
                                capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads((folder / "status.json").read_text())["status"], "failed")
        self.assertEqual(source.read_bytes(), b"source stays unchanged")

    def test_dependency_archive_escape(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("../escape.txt", "escape")
        with self.assertRaises(ValueError):
            safe_extract(data.getvalue(), self.base / "extract")
        self.assertFalse((self.base / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
