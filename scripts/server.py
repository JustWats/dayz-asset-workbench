"""Local DayZ asset MCP: native conversion/viewers and Blender asset jobs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal
import uuid

from mcp.server.fastmcp import FastMCP, Image
from common import (HERE, SETTINGS, RUNTIME, DEFAULT_PROJECT, project_path, read_path,
                    lock_for, write_json, hidden_options, blender_call, execute, live_project)

mcp = FastMCP("DayZ Asset Workbench")


def new_job(project, operation, arguments):
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:10]
    folder = project / "work/mcp" / job_id
    folder.mkdir(parents=True, exist_ok=False)
    request = {"job_id": job_id, "project": str(project), "operation": operation, "arguments": arguments}
    write_json(folder / "request.json", request)
    write_json(folder / "status.json", {"job_id": job_id, "status": "queued"})
    return folder


def launch_job(folder):
    with (folder / "worker.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(HERE / "job_runner.py"), str(folder / "request.json")],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=HERE, **hidden_options())
    return {"job_id": folder.name, "status": "started", "pid": process.pid,
            "output_directory": str(folder), "next_tool": "get_asset_job"}


@mcp.tool()
def asset_status(project: str = DEFAULT_PROJECT) -> dict:
    """Check Blender MCP connection, installed DayZ tools and latest prepared asset paths."""
    root = project_path(project)
    lock = lock_for(root)
    tools = {"blender": lock["blender"]["path"]}
    for key, rel in {"object_builder": "ObjectBuilder/ObjectBuilder.exe", "texview": "ImageToPAA/TexView.exe",
                     "image_to_paa": "ImageToPAA/ImageToPAA.exe", "cfg_convert": "CfgConvert/CfgConvert.exe"}.items():
        tools[key] = str(Path(lock["dayz_tools"]) / "Bin" / rel)
    try:
        live = blender_call("get_scene_info")
    except Exception as error:
        live = {"connected": False, "reason": str(error), "next_tool": "start_blender_session"}
    latest = root / "reports/preparation-latest.json"
    return {"project": str(root), "tools": {k: {"path": v, "exists": Path(v).is_file()} for k, v in tools.items()},
            "blender_scene": live, "latest": json.loads(latest.read_text()) if latest.exists() else None}


@mcp.tool()
def start_blender_session(project: str = DEFAULT_PROJECT, blend_path: str = "") -> dict:
    """Open a dedicated visible Blender editor with MCP and P3D addon enabled. Reuses an existing bridge without replacing its scene."""
    root = project_path(project)
    try:
        live = blender_call("get_scene_info")
        return {"status": "already_running", "scene": live,
                "note": "Existing scene was preserved; no requested file was loaded."}
    except (OSError, RuntimeError):
        pass
    latest_path = root / "reports/preparation-latest.json"
    if not blend_path and latest_path.is_file():
        blend_path = json.loads(latest_path.read_text())["blend"]
    path = read_path(blend_path, root, {".blend"}) if blend_path else None
    lock = lock_for(root)
    profile = RUNTIME / "blender-profile"
    for sub in ("config", "scripts"):
        (profile / sub).mkdir(parents=True, exist_ok=True)
    import os
    env = dict(os.environ, BLENDER_USER_CONFIG=str(profile / "config"),
               BLENDER_USER_SCRIPTS=str(profile / "scripts"), BLENDER_MCP_DISABLE_TELEMETRY="1")
    log_path = root / "reports/blender-mcp-session.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([lock["blender"]["path"], "--factory-startup", *([str(path)] if path else []),
                                   "--python", str(HERE / "blender_startup.py"), "--", str(root)],
                                  cwd=root, env=env, stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=subprocess.STDOUT)
    return {"status": "starting", "pid": process.pid, "file": str(path), "log": str(log_path),
            "next_tool": "asset_status"}


@mcp.tool()
def convert_texture(source: str, output_format: Literal["paa", "png", "tga"] = "paa",
                    suffix: Literal["co", "ca", "nohq", "smdi", "as", "em", "preserve"] = "preserve",
                    project: str = DEFAULT_PROJECT) -> dict:
    """Convert PNG/TGA/PAA using native DayZ ImageToPAA. New output only. A suffix selects encoding rules; it does not repack PBR channels."""
    root = project_path(project)
    path = read_path(source, root, {".png", ".tga", ".paa", ".pac", ".jpg", ".jpeg"})
    if output_format == "paa" and suffix == "preserve" and not re.search(r"_(co|ca|nohq|smdi|as|em)$", path.stem, re.I):
        raise ValueError("Choose the DayZ texture suffix explicitly for an unclassified source")
    return launch_job(new_job(root, "texture", {"source": str(path), "format": output_format, "suffix": suffix}))


@mcp.tool()
def inspect_p3d(source: str, project: str = DEFAULT_PROJECT) -> dict:
    """Read an editable MLOD P3D: LODs, vertices/faces, materials, selections and mass tags. No file modification."""
    root = project_path(project)
    path = read_path(source, root, {".p3d"})
    with path.open("rb") as stream:
        if stream.read(4) != b"MLOD":
            raise ValueError("This inspector supports editable MLOD only; an ODOL requires a separate reference reader")
    return launch_job(new_job(root, "inspect_p3d", {"source": str(path)}))


@mcp.tool()
def import_asset(source: str, project: str = DEFAULT_PROJECT) -> dict:
    """Append FBX, OBJ, or editable P3D to the active Blender scene. Keeps existing objects and returns newly imported names."""
    root = project_path(project)
    path = read_path(source, root, {".fbx", ".obj", ".p3d"})
    live_project(root)
    operations = {".fbx": "bpy.ops.import_scene.fbx", ".obj": "bpy.ops.import_scene.obj", ".p3d": "bpy.ops.a3ob.import_p3d"}
    if path.suffix.lower() == ".p3d":
        with path.open("rb") as stream:
            if stream.read(4) != b"MLOD":
                raise ValueError("Only editable MLOD import is supported by the selected exporter")
    code = ("import bpy, json\nbefore=set(bpy.data.objects)\n" + operations[path.suffix.lower()] +
            "(filepath=" + repr(str(path)) + ")\nprint(json.dumps({'imported':[o.name for o in set(bpy.data.objects)-before]}))")
    return execute(code)


@mcp.tool()
def export_active_p3d(objects: list[str] | None = None,
                      mode: Literal["visual_color", "configured_lods"] = "visual_color",
                      texture_root: str = "", project: str = DEFAULT_PROJECT) -> dict:
    """Snapshot live Blender and export P3D in a background job. visual_color makes one visual LOD and PAA color maps; configured_lods preserves authored LODs/material paths. Does not alter the live scene or overwrite files."""
    root = project_path(project)
    live_project(root)
    if texture_root:
        drive = Path(texture_root).resolve()
        if not drive.is_relative_to(root) or not drive.is_dir():
            raise ValueError("Texture root must be an existing project directory")
    elif mode == "configured_lods":
        raise ValueError("Configured LOD export requires the existing texture/project drive root")
    folder = new_job(root, "export_p3d", {"objects": objects or [], "mode": mode, "texture_root": texture_root})
    snapshot = folder / "scene_snapshot.blend"
    try:
        execute("import bpy\nbpy.ops.wm.save_as_mainfile(filepath=" + repr(str(snapshot)) + ", copy=True)")
        if not snapshot.exists():
            raise RuntimeError("Blender did not save the scene snapshot")
    except Exception as error:
        write_json(folder / "status.json", {"status": "failed", "error": str(error)})
        raise
    return launch_job(folder)


@mcp.tool()
def get_asset_job(job_id: str, project: str = DEFAULT_PROJECT) -> dict:
    """Check a conversion/export job and retrieve output paths or its failure and log tail. Poll after useful independent work."""
    root = project_path(project)
    if not re.fullmatch(r"\d{8}T\d{6}_[0-9a-f]{10}", job_id):
        raise ValueError("Invalid job id")
    folder = root / "work/mcp" / job_id
    status = json.loads((folder / "status.json").read_text())
    status["job_id"] = job_id
    log = folder / "tool.log"
    if log.exists():
        status["log_tail"] = log.read_text(encoding="utf-8", errors="replace")[-3000:]
    return status


@mcp.tool()
def get_asset_preview(source: str, project: str = DEFAULT_PROJECT) -> Image:
    """Return a generated PNG preview directly as an MCP image. Convert a PAA to PNG first with convert_texture."""
    root = project_path(project)
    path = read_path(source, root, {".png", ".jpg", ".jpeg"})
    return Image(path=str(path))


@mcp.tool()
def open_native_viewer(source: str, viewer: Literal["object_builder", "texview"] = "object_builder",
                       project: str = DEFAULT_PROJECT) -> dict:
    """Open a P3D in native Object Builder or an image/PAA in native TexView for interactive inspection. Launching does not imply rendered verification."""
    root = project_path(project)
    extensions = {".p3d"} if viewer == "object_builder" else {".paa", ".pac", ".png", ".tga"}
    path = read_path(source, root, extensions)
    rel = "ObjectBuilder/ObjectBuilder.exe" if viewer == "object_builder" else "ImageToPAA/TexView.exe"
    executable = Path(lock_for(root)["dayz_tools"]) / "Bin" / rel
    process = subprocess.Popen([str(executable), str(path)], cwd=executable.parent,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"status": "launched", "pid": process.pid, "viewer": viewer, "asset": str(path)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
