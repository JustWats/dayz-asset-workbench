"""P3D jobs using the reviewed Arma3ObjectBuilder codec, never a bespoke codec."""
import addon_utils
import bpy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import exporter_directory, hidden_options

request_path = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
request = json.loads(request_path.read_text())
project = Path(request["project"]).resolve()
folder = request_path.parent
args = request["arguments"]
lock = json.loads((project / "config/toolchain.lock.json").read_text())
sys.path.insert(0, str(exporter_directory(project).parent))
addon_utils.enable("Arma3ObjectBuilder", default_set=True, persistent=False)
import Arma3ObjectBuilder as a3ob


def inspect(path):
    model = a3ob.io.data_p3d.P3D_MLOD.read_file(str(path))
    lods = []
    for lod in model.lods:
        lods.append({"resolution": float(lod.resolution), "vertices": len(lod.verts),
                     "faces": len(lod.faces), "triangles": sum(len(f[0]) - 2 for f in lod.faces),
                     "materials": sorted({(f[3], f[4]) for f in lod.faces}),
                     "tags": [tag.name for tag in lod.taggs]})
    if not lods:
        raise RuntimeError("Empty P3D")
    return {"file": str(path), "format": "MLOD", "lod_count": len(lods), "lods": lods}


if request["operation"] == "inspect_p3d":
    result = inspect(Path(args["source"]))
else:
    bpy.ops.object.select_all(action="DESELECT")
    chosen = args["objects"]
    if chosen:
        missing = [name for name in chosen if name not in bpy.context.scene.objects]
        if missing:
            raise ValueError(f"Unknown mesh names: {missing}")
    candidates = [o for o in bpy.context.scene.objects if o.type == "MESH" and (not chosen or o.name in chosen)]
    if not candidates:
        raise ValueError("No meshes available for export")
    # Authored LODs are commonly hidden while editing. Selection-based export must
    # include them in the isolated snapshot, without changing the live viewport.
    for obj in candidates:
        obj.hide_set(False)
        obj.hide_viewport = False
    texture_outputs = []
    required_resolutions = []
    if args["mode"] == "visual_color":
        stage = folder / "stage"
        prefix = re.sub(r"[^A-Za-z0-9_]", "_", project.name)
        data = stage / prefix / "data"
        data.mkdir(parents=True)
        used = {m for obj in candidates for m in obj.data.materials if m}
        for i, mat in enumerate(sorted(used, key=lambda m: m.name)):
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.use_nodes else None
            incoming = bsdf.inputs["Base Color"].links if bsdf else []
            image = incoming[0].from_node.image if incoming and incoming[0].from_node.type == "TEX_IMAGE" else None
            if not image:
                raise ValueError(f"Material {mat.name} needs a direct Base Color image for visual_color export")
            source = Path(bpy.path.abspath(image.filepath)).resolve()
            # This convenience mode copies existing local color images; no PBR-map guessing.
            if not source.is_file() or not source.is_relative_to(project):
                raise ValueError(f"Material {mat.name} needs an image file inside the project")
            stem = re.sub(r"[^a-z0-9]+", "_", mat.name.lower()).strip("_") + f"_{i}_co"
            png = data / (stem + source.suffix.lower())
            shutil.copyfile(source, png)
            paa = data / (stem + ".paa")
            exe = Path(lock["dayz_tools"]) / "Bin/ImageToPAA/ImageToPAA.exe"
            subprocess.run([str(exe), str(png), str(paa)], cwd=exe.parent, check=True,
                           timeout=120, **hidden_options())
            if not paa.is_file():
                raise RuntimeError("PAA conversion failed")
            mat.a3ob_properties_material.texture_path = str(paa)
            mat.a3ob_properties_material.texture_type = "TEX"
            mat.a3ob_properties_material.material_path = ""
            texture_outputs.append(str(paa))
        for obj in candidates:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = candidates[0]
        bpy.ops.object.join()
        obj = bpy.context.object
        obj.a3ob_properties_object.is_a3_lod = True
        obj.a3ob_properties_object.lod = "0"
        obj.a3ob_properties_object.resolution = 0
        obj.name = "Visual_LOD0_TEST"
        a3ob.get_prefs().project_root = str(stage)
        output = stage / prefix / "asset.p3d"
    else:
        lods = [o for o in candidates if o.a3ob_properties_object.is_a3_lod]
        if not lods:
            raise ValueError("No authored P3D LOD objects. Assign LOD metadata before configured_lods export")
        for obj in lods:
            for prop in [obj.a3ob_properties_object, *obj.a3ob_properties_object.copies]:
                resolution = prop.resolution_float if prop.lod == '-1' else prop.resolution
                required_resolutions.append(float(a3ob.io.data_p3d.P3D_LOD_Resolution(int(prop.lod), resolution)))
        for obj in lods:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = lods[0]
        a3ob.get_prefs().project_root = args["texture_root"]
        output = folder / "asset.p3d"
    status = bpy.ops.a3ob.export_p3d(filepath=str(output), use_selection=True, relative_paths=True,
                                    validate_meshes=True, validate_lods=True, force_lowercase=True)
    if "FINISHED" not in status:
        raise RuntimeError("P3D export failed")
    result = inspect(output)
    from collections import Counter
    missing = Counter(required_resolutions) - Counter(lod['resolution'] for lod in result['lods'])
    if missing:
        raise RuntimeError(f"Exporter skipped requested LODs after validation: {dict(missing)}. Inspect tool.log; partial output is not accepted.")
    result["textures"] = texture_outputs
    result["mode"] = args["mode"]
    result["game_ready"] = False
    result["notes"] = ["MLOD interchange validated; engine rendering and item configuration still require DayZ testing."]
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "export_scene.blend"))
(folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("DAYZ_ASSET_JOB_OK")
