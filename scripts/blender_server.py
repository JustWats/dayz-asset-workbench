"""Expose only the local editing/inspection tools from the pinned Blender MCP."""
import asyncio
import os

os.environ["BLENDER_MCP_DISABLE_TELEMETRY"] = "1"
from blender_mcp.server import mcp

LOCAL_TOOLS = {"get_scene_info", "get_object_info", "get_viewport_screenshot", "execute_blender_code"}


async def configure():
    for tool in await mcp.list_tools():
        if tool.name not in LOCAL_TOOLS:
            mcp.remove_tool(tool.name)


if __name__ == "__main__":
    asyncio.run(configure())
    mcp.run(transport="stdio")
