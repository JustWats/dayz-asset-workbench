"""Real MCP round trip against an installed toolchain and its active project scene.

Creates isolated export jobs, briefly imports the exported P3D, then removes only
the imported objects. Never saves over the open Blender file. Logs/assets are local.
"""
import argparse
import asyncio
import base64
from contextlib import AsyncExitStack
from datetime import timedelta
import json
import os
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(args):
    config = json.loads(Path(args.config).read_text())["mcpServers"]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "jobs": []}
    async with AsyncExitStack() as stack:
        sessions = {}
        for name, server in config.items():
            read, write = await stack.enter_async_context(stdio_client(StdioServerParameters(
                command=server["command"], args=server["args"], env={**os.environ, **server.get("env", {})})))
            session = await stack.enter_async_context(ClientSession(read, write, read_timeout_seconds=timedelta(seconds=90)))
            await session.initialize()
            sessions[name] = session
            report[name] = [t.name for t in (await session.list_tools()).tools]

        async def call(server, tool, **params):
            result = await sessions[server].call_tool(tool, params)
            if result.isError:
                raise RuntimeError(str(result.content))
            if result.content[0].type == "image":
                path = output / (tool + ".png")
                path.write_bytes(base64.b64decode(result.content[0].data))
                assert path.stat().st_size > 100
                return str(path)
            text = result.content[0].text
            if text.startswith(("Error", "Rejected")):
                raise RuntimeError(text)
            try:
                return json.loads(text)
            except ValueError:
                return text

        async def job(tool, **params):
            started = await call("dayz_assets", tool, **params)
            report["jobs"].append(started["job_id"])
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                status = await call("dayz_assets", "get_asset_job", job_id=started["job_id"])
                if status["status"] == "completed":
                    report["checks"].append(tool)
                    print("PASS", tool, flush=True)
                    return status["result"]
                if status["status"] == "failed":
                    raise RuntimeError(status)
                await asyncio.sleep(1)
            raise TimeoutError(started)

        await call("dayz_assets", "asset_status")
        before = await call("blender", "get_scene_info", user_prompt="Test the local MCP tools.")
        exported = await job("export_active_p3d")
        inspected = await job("inspect_p3d", source=exported["file"])
        assert inspected["lods"] == exported["lods"]
        assert exported["textures"], "Use a scene with at least one Base Color image material"
        decoded = await job("convert_texture", source=exported["textures"][0], output_format="png")
        await call("dayz_assets", "get_asset_preview", source=decoded["output"])
        encoded = await job("convert_texture", source=decoded["output"], output_format="paa")
        assert Path(encoded["output"]).stat().st_size > 16
        imported = []
        try:
            raw = await call("dayz_assets", "import_asset", source=exported["file"])
            imported = json.loads(raw["result"].strip().splitlines()[-1])["imported"]
            assert imported
            await call("blender", "get_object_info", object_name=imported[0], user_prompt="Test the local MCP tools.")
            # The imported P3D is one directory below the virtual addon root.
            configured = await job("export_active_p3d", objects=imported, mode="configured_lods",
                                   texture_root=str(Path(exported["file"]).parents[1]))
            assert configured["lods"] == exported["lods"], "P3D round trip changed geometry/material metadata"
            report["checks"].append("import_and_configured_export_roundtrip")
        finally:
            if imported:
                code = "import bpy\nfor name in " + repr(imported) + ":\n    obj=bpy.data.objects.get(name)\n    if obj: bpy.data.objects.remove(obj, do_unlink=True)\nprint('import cleanup complete')"
                await call("blender", "execute_blender_code", code=code, user_prompt="Test the local MCP tools.")
        after = await call("blender", "get_scene_info", user_prompt="Test the local MCP tools.")
        assert after["object_count"] == before["object_count"]
        await call("blender", "get_viewport_screenshot", max_size=1000, user_prompt="Test the local MCP tools.")
        if args.open_viewers:
            await call("dayz_assets", "open_native_viewer", source=exported["file"], viewer="object_builder")
            await call("dayz_assets", "open_native_viewer", source=exported["textures"][0], viewer="texview")
            report["checks"].append("native_viewer_launch_only")
        report["status"] = "passed"
        report["geometry"] = exported["lods"]
        (output / "integration.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": "passed", "report": str(output / "integration.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / ".mcp.json"))
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "reports/integration"))
    parser.add_argument("--open-viewers", action="store_true")
    asyncio.run(main(parser.parse_args()))
