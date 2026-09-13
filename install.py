"""Install the local MCP runtime and generate machine-specific STDIO configuration."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile

ROOT = Path(__file__).resolve().parent
PINS = json.loads((ROOT / "dependencies.json").read_text())


def safe_extract(data, destination):
    destination = destination.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination) or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe path in dependency archive")
        archive.extractall(destination)


def restore_dependency(pin, target, runtime, expected_folder=None):
    marker = target / ".dayz-workbench-pin.json"
    if marker.is_file() and json.loads(marker.read_text()).get("sha256") == pin["sha256"]:
        return
    if target.exists():
        raise ValueError(f"Unmanaged dependency directory exists: {target}. Choose another runtime directory.")
    request = urllib.request.Request(pin["url"], headers={"User-Agent": "dayz-asset-workbench-installer"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("Dependency download does not match its pinned SHA256")
    # Temporary cleanup is restricted to this uniquely created runtime child.
    with tempfile.TemporaryDirectory(prefix="dependency-", dir=runtime) as temp:
        stage = Path(temp)
        safe_extract(data, stage)
        if expected_folder:
            source = stage / expected_folder
        else:
            directories = [p for p in stage.iterdir() if p.is_dir()]
            if len(directories) != 1:
                raise ValueError("Unexpected archive structure")
            source = directories[0]
        if not source.is_dir():
            raise ValueError("Archive is missing the expected package")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Both absolute paths are children of the selected runtime directory.
        if not source.resolve().is_relative_to(runtime) or not target.resolve().is_relative_to(runtime):
            raise ValueError("Dependency paths must remain in runtime")
        shutil.move(str(source), str(target))
    marker.write_text(json.dumps(pin, indent=2) + "\n")


def write_local(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            shutil.copyfile(path, backup)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--blender", type=Path, help="Blender executable; inferred from an existing toolchain lock")
    parser.add_argument("--dayz-tools", type=Path, help="DayZ Tools directory; inferred from an existing toolchain lock")
    parser.add_argument("--workspace", type=Path, help="Allowed project parent, defaults to the project itself")
    parser.add_argument("--reference-root", action="append", type=Path, default=[])
    parser.add_argument("--runtime", type=Path, default=Path.home() / ".local/share/dayz-asset-workbench")
    parser.add_argument("--port", type=int, default=9876)
    args = parser.parse_args()
    if os.name != "nt" or sys.version_info < (3, 11):
        parser.error("This native DayZ toolchain requires Windows and Python 3.11 or newer")
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be 1024..65535")
    project = args.project.resolve()
    workspace = (args.workspace or project).resolve()
    if not project.is_relative_to(workspace):
        parser.error("Project must be inside workspace")
    lock_path = project / "config/toolchain.lock.json"
    lock = json.loads(lock_path.read_text()) if lock_path.is_file() else {}
    blender_value = args.blender or lock.get("blender", {}).get("path")
    dayz_value = args.dayz_tools or lock.get("dayz_tools")
    if not blender_value or not dayz_value:
        parser.error("Supply --blender and --dayz-tools when creating a new project")
    blender = Path(blender_value).resolve()
    dayz = Path(dayz_value).resolve()
    executables = [blender, dayz / "Bin/ImageToPAA/ImageToPAA.exe",
                   dayz / "Bin/ImageToPAA/TexView.exe", dayz / "Bin/ObjectBuilder/ObjectBuilder.exe"]
    missing = [str(p) for p in executables if not p.is_file()]
    if missing:
        parser.error("Missing required installed tools: " + ", ".join(missing))
    for reference in args.reference_root:
        if not reference.is_dir():
            parser.error(f"Reference root does not exist: {reference}")
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    upstream = runtime / "blender-mcp"
    exporter = runtime / "addons/Arma3ObjectBuilder"
    restore_dependency(PINS["blender_mcp"], upstream, runtime)
    restore_dependency(PINS["exporter"], exporter, runtime, "Arma3ObjectBuilder")
    environment = runtime / "venv"
    python = environment / "Scripts/python.exe"
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.lock.txt")], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(upstream)], check=True)
    lock.setdefault("blender", {})["path"] = str(blender)
    lock["dayz_tools"] = str(dayz)
    write_local(lock_path, lock)
    settings = {"workspace_root": str(workspace), "default_project": str(project),
                "runtime_root": str(runtime), "exporter_directory": str(exporter),
                "reference_roots": [str(p.resolve()) for p in args.reference_root],
                "blender_host": "127.0.0.1", "blender_port": args.port}
    settings_path = ROOT / "scripts/settings.json"
    write_local(settings_path, settings)
    env = {"DAYZ_ASSET_SETTINGS": str(settings_path)}
    config = {"mcpServers": {
        "dayz_assets": {"command": str(python), "args": [str(ROOT / "scripts/server.py")], "env": env},
        "blender": {"command": str(python), "args": [str(ROOT / "scripts/blender_server.py")],
                    "env": {**env, "BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": str(args.port),
                            "BLENDER_MCP_DISABLE_TELEMETRY": "1"}}}}
    write_local(ROOT / ".mcp.json", config)
    print(json.dumps({"status": "installed", "mcp_config": str(ROOT / ".mcp.json"),
                      "python": str(python), "servers": list(config["mcpServers"])}, indent=2))


if __name__ == "__main__":
    main()
