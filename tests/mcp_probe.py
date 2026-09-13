"""Exercise a configured MCP server over real STDIO; optionally persist images/results."""
import argparse
import asyncio
import base64
from datetime import timedelta
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(args):
    config = json.loads(Path(args.config).read_text())["mcpServers"][args.server]
    params = StdioServerParameters(command=config["command"], args=config["args"],
                                   env={**os.environ, **config.get("env", {})})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=90)) as session:
            await session.initialize()
            if args.tool:
                result = await session.call_tool(args.tool, json.loads(args.arguments))
                report = result.model_dump(mode="json", exclude_none=True)
                for i, block in enumerate(report.get("content", [])):
                    if block.get("type") == "image":
                        data = base64.b64decode(block.pop("data"))
                        block["bytes"] = len(data)
                        if args.output:
                            ext = ".png" if block["mimeType"] == "image/png" else ".jpg"
                            path = Path(args.output).with_suffix(f".{i}" + ext)
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(data)
                            block["path"] = str(path)
            else:
                result = await session.list_tools()
                report = {"tools": [tool.name for tool in result.tools]}
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
            if report.get("isError"):
                raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / ".mcp.json"))
    parser.add_argument("--server", default="dayz_assets", choices=["dayz_assets", "blender"])
    parser.add_argument("--tool")
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--output")
    asyncio.run(run(parser.parse_args()))
