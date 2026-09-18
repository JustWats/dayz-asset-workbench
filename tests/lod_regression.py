"""Real MCP regression: hidden LOD inclusion and rejection of partial exports."""
import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
import json
import os
from pathlib import Path
import time
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / '.mcp.json').read_text())['mcpServers']
    async with AsyncExitStack() as stack:
        sessions = {}
        for name, entry in config.items():
            read, write = await stack.enter_async_context(stdio_client(StdioServerParameters(
                command=entry['command'], args=entry['args'], env={**os.environ, **entry.get('env', {})})))
            session = await stack.enter_async_context(ClientSession(read,write,read_timeout_seconds=timedelta(seconds=90)))
            await session.initialize()
            sessions[name] = session

        async def call(server, tool, **arguments):
            result = await sessions[server].call_tool(tool, arguments)
            if result.isError:
                raise RuntimeError(str(result.content))
            text = result.content[0].text
            if text.startswith('Error'):
                raise RuntimeError(text)
            try:
                return json.loads(text)
            except ValueError:
                return text

        async def terminal(started):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                value = await call('dayz_assets','get_asset_job',job_id=started['job_id'])
                if value['status'] in ('completed','failed'):
                    return value
                await asyncio.sleep(1)
            raise TimeoutError(started)

        project = (await call('dayz_assets','asset_status'))['project']
        names = ['MCP_LOD_' + uuid.uuid4().hex[:10] + '_' + n for n in ('visible','hidden','invalid')]
        script = """import bpy
names = NAMES
for i,name in enumerate(names):
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata([(0,0,0),(.01,0,0),(.01,.01,0),(0,.01,0)],[],[(0,1,2,3)])
    obj=bpy.data.objects.new(name,mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.a3ob_properties_object.is_a3_lod=True
    obj.a3ob_properties_object.lod='0' if i<2 else '4'
    obj.a3ob_properties_object.resolution=201+i if i<2 else 0
    obj.hide_set(i==1)
print('LOD fixtures created')
""".replace('NAMES',repr(names))
        jobs = []
        try:
            await call('blender','execute_blender_code',code=script,user_prompt='Test hidden and invalid LOD export handling.')
            started = await call('dayz_assets','export_active_p3d',objects=names[:2],mode='configured_lods',texture_root=project)
            jobs.append(started['job_id'])
            valid = await terminal(started)
            assert valid['status']=='completed',valid
            assert sorted(l['resolution'] for l in valid['result']['lods'])==[201,202],valid
            started = await call('dayz_assets','export_active_p3d',objects=names,mode='configured_lods',texture_root=project)
            jobs.append(started['job_id'])
            invalid = await terminal(started)
            assert invalid['status']=='failed',invalid
            assert 'Exporter skipped requested LODs' in invalid.get('log_tail',''),invalid
            print(json.dumps({'status':'passed','hidden_lod_included':True,'partial_export_rejected':True,'jobs':jobs}))
        finally:
            cleanup = "import bpy\nfor name in " + repr(names) + ":\n    obj=bpy.data.objects.get(name)\n    if obj:\n        mesh=obj.data\n        bpy.data.objects.remove(obj,do_unlink=True)\n        if mesh.users==0: bpy.data.meshes.remove(mesh)\nprint('LOD fixtures removed')"
            await call('blender','execute_blender_code',code=cleanup,user_prompt='Remove only the temporary LOD test fixtures.')


if __name__ == '__main__':
    asyncio.run(main())
