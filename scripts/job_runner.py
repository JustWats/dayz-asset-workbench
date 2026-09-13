"""Detached worker for MCP jobs; every job has a durable status and tool log."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import traceback

from common import HERE, project_path, read_path, lock_for, write_json, hidden_options


def main():
    request_path = Path(sys.argv[1]).resolve()
    request = json.loads(request_path.read_text())
    project = project_path(request["project"])
    folder = request_path.parent
    if folder.parent != project / "work/mcp":
        raise ValueError("Invalid job directory")
    status_path = folder / "status.json"
    write_json(status_path, {"status": "running", "operation": request["operation"]})
    lock = lock_for(project)
    args = request["arguments"]
    try:
        operation = request["operation"]
        result = {}
        if operation == "texture":
            source = read_path(args["source"], project)
            stem = source.stem
            if args["suffix"] != "preserve":
                stem = re.sub(r"_(co|ca|nohq|smdi|as|em)$", "", stem, flags=re.I) + "_" + args["suffix"]
            staged = folder / "input" / (stem + source.suffix)
            staged.parent.mkdir()
            shutil.copyfile(source, staged)
            output = folder / (stem + "." + args["format"])
            exe = Path(lock["dayz_tools"]) / "Bin/ImageToPAA/ImageToPAA.exe"
            command = [str(exe), str(staged), str(output)]
            cwd = exe.parent
            result = {"output": str(output), "source": str(source), "channel_repacking": False}
        elif operation in ("inspect_p3d", "export_p3d"):
            command = [lock["blender"]["path"], "--background", "--factory-startup"]
            if operation == "export_p3d":
                command.append(str(folder / "scene_snapshot.blend"))
            command += ["--python-exit-code", "1", "--python", str(HERE / "blender_job.py"), "--", str(request_path)]
            cwd = project
        else:
            raise ValueError("Unknown asset job operation")
        with (folder / "tool.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, timeout=600, **hidden_options())
        if completed.returncode:
            raise RuntimeError(f"Native tool exited with code {completed.returncode}")
        if operation == "texture":
            if not output.is_file() or output.stat().st_size < 16:
                raise RuntimeError("Native texture converter did not produce valid output")
            result["bytes"] = output.stat().st_size
        else:
            result = json.loads((folder / "result.json").read_text())
        write_json(status_path, {"status": "completed", "operation": operation, "result": result})
    except Exception as error:
        write_json(status_path, {"status": "failed", "error": str(error)})
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
