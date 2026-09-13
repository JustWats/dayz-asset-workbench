import json
import os
from pathlib import Path
import socket
import subprocess

HERE = Path(__file__).resolve().parent
SETTINGS_PATH = Path(os.environ.get("DAYZ_ASSET_SETTINGS", HERE / "settings.json"))
SETTINGS = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
DEFAULT_PROJECT = SETTINGS["default_project"]
RUNTIME = Path(SETTINGS["runtime_root"])


def project_path(value=DEFAULT_PROJECT):
    path = Path(value).resolve()
    if not path.is_relative_to(Path(SETTINGS["workspace_root"]).resolve()):
        raise ValueError("Project must be inside the configured workspace")
    if not (path / "config/toolchain.lock.json").is_file():
        raise ValueError(f"Project has no toolchain.lock.json: {path}")
    return path


def read_path(value, project, suffixes=None):
    path = Path(value)
    if not path.is_absolute():
        path = project / path
    path = path.resolve()
    allowed = [project, *[Path(x).resolve() for x in SETTINGS["reference_roots"]]]
    if not any(path.is_relative_to(root) for root in allowed):
        raise ValueError("Asset must be inside the project or configured DayZ reference roots")
    if not path.is_file():
        raise FileNotFoundError(path)
    if suffixes and path.suffix.lower() not in suffixes:
        raise ValueError(f"Unsupported asset extension {path.suffix}")
    return path


def lock_for(project):
    return json.loads((project / "config/toolchain.lock.json").read_text())


def exporter_directory(project):
    configured = SETTINGS.get("exporter_directory")
    return Path(configured) if configured else project / "vendor/Arma3ObjectBuilder"


def write_json(path, data):
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def hidden_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}


def blender_call(command, params=None, timeout=30):
    """Use the reviewed blender-mcp addon's documented JSON socket protocol."""
    with socket.create_connection((SETTINGS["blender_host"], SETTINGS["blender_port"]), timeout=3) as connection:
        connection.settimeout(timeout)
        connection.sendall(json.dumps({"type": command, "params": params or {}}).encode())
        received = bytearray()
        while len(received) < 16 * 1024 * 1024:
            chunk = connection.recv(65536)
            if not chunk:
                raise RuntimeError("Blender disconnected before returning a result")
            received.extend(chunk)
            try:
                data = json.loads(received)
            except (ValueError, UnicodeDecodeError):
                continue
            if data.get("status") == "error":
                raise RuntimeError(data.get("message", str(data)))
            return data.get("result", data)
        raise RuntimeError("Blender response exceeds the configured limit")


def execute(code, timeout=30):
    return blender_call("execute_code", {"code": code}, timeout)


def live_project(project):
    result = execute("import bpy, json\nprint(json.dumps({'project': bpy.context.scene.get('dayz_asset_project', '')}))")
    output = result.get("result", "")
    state = json.loads(output.strip())
    if Path(state["project"]).resolve() != project:
        raise ValueError("Live Blender belongs to another project. Use that project or start its own session.")
