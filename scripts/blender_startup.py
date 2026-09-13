"""Enable the pinned addons for a dedicated interactive Blender session."""
import addon_utils
import bpy
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import SETTINGS as settings, exporter_directory
project = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
runtime = Path(settings["runtime_root"])
sys.path.insert(0, str(exporter_directory(project).parent))
sys.path.insert(0, str(runtime / "blender-mcp"))
addon_utils.enable("Arma3ObjectBuilder", default_set=True, persistent=True)
bpy.context.scene["blendermcp_auto_start_server"] = False
addon_utils.enable("addon", default_set=True, persistent=True)
import addon

prefs = bpy.context.preferences.addons["addon"].preferences
prefs.telemetry_consent = False
scene = bpy.context.scene
scene.blendermcp_auto_start_server = False
if getattr(bpy.types, "blendermcp_server", None):
    bpy.types.blendermcp_server.stop()
for name in ("blendermcp_use_polyhaven", "blendermcp_use_sketchfab", "blendermcp_use_polypizza",
             "blendermcp_use_hyper3d", "blendermcp_use_hunyuan3d"):
    if hasattr(scene, name):
        setattr(scene, name, False)
scene["dayz_asset_project"] = str(project)
scene.blendermcp_port = settings["blender_port"]
bpy.types.blendermcp_server = addon.BlenderMCPServer(settings["blender_host"], settings["blender_port"])
bpy.types.blendermcp_server.start()
scene.blendermcp_server_running = bpy.types.blendermcp_server.running
if not scene.blendermcp_server_running:
    raise RuntimeError("Blender MCP listener failed to start")

# Put the prepared asset in a useful initial viewport, without modifying geometry.
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.region_3d.view_perspective = "CAMERA" if scene.camera else "PERSP"
            space.shading.type = "MATERIAL"
            space.overlay.show_overlays = False
print("DAYZ_ASSET_MCP_READY", settings["blender_host"], settings["blender_port"], flush=True)
