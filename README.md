# DayZ Asset Workbench

Local MCP tools for editing Blender scenes, converting DayZ textures, exporting editable P3D models, and opening Object Builder or TexView. Windows only. This repository contains reusable tooling; no mod content or purchased assets.

Two STDIO MCP servers expose 13 tools. The Blender side uses a pinned [Blender MCP](https://github.com/ahujasid/blender-mcp) with four local tools enabled. P3D jobs use [Arma 3 Object Builder](https://github.com/MrClock8163/Arma3ObjectBuilder/releases/tag/v2.5.1) inside Blender. Texture conversion uses your installed DayZ Tools `ImageToPAA.exe`.

## Tools

| Server | Tool | Purpose |
| --- | --- | --- |
| `dayz_assets` | `asset_status` | Check native executables and the live Blender connection. |
| `dayz_assets` | `start_blender_session` | Start a visible Blender editor with both addons enabled in an isolated profile. |
| `dayz_assets` | `import_asset` | Append FBX, OBJ, or editable MLOD P3D to the current project scene. |
| `dayz_assets` | `export_active_p3d` | Snapshot the live scene and export P3D in a background job. |
| `dayz_assets` | `inspect_p3d` | Report LODs, geometry counts, material paths, and tag names from MLOD P3D. |
| `dayz_assets` | `convert_texture` | Convert PNG/TGA/JPEG/PAA using native ImageToPAA, with PAA/PNG/TGA output. |
| `dayz_assets` | `get_asset_job` | Retrieve durable job status, outputs, or failure details. |
| `dayz_assets` | `get_asset_preview` | Return a PNG/JPEG as an MCP image. |
| `dayz_assets` | `open_native_viewer` | Launch Object Builder with a P3D, or TexView with a texture. |
| `blender` | `get_scene_info` | Inspect the live scene. |
| `blender` | `get_object_info` | Inspect a particular object. |
| `blender` | `get_viewport_screenshot` | Return the actual Blender viewport as an MCP image. |
| `blender` | `execute_blender_code` | Edit the scene through Blender's Python API. |

## Install

Requires installed Blender, DayZ Tools, and Python 3.11+. The verified combination is Windows 11, Python 3.11, Blender 3.5.0, and Arma 3 Object Builder 2.5.1. Later Blender releases have changed import operators and are not yet validated here.

Clone the repository and run these commands in **PowerShell**:

```powershell
git clone https://github.com/JustWats/dayz-asset-workbench.git
Set-Location dayz-asset-workbench
python install.py --project D:/DayZProjects/MyMod --blender 'C:/Program Files/Blender Foundation/Blender 3.5/blender.exe' --dayz-tools 'D:/SteamLibrary/steamapps/common/DayZ Tools'
```

For an existing project with `config/toolchain.lock.json`, only `--project` is required. Optional arguments are `--workspace`, repeated `--reference-root`, `--runtime`, and `--port`. Run `python install.py --help` for details.

The installer downloads checksum-pinned addons, creates its own Python environment, and writes these local files:

- `.mcp.json`: both STDIO server entries with absolute paths.
- `scripts/settings.json`: allowed project/reference roots, runtime path, and loopback port.
- `<project>/config/toolchain.lock.json`: native tool paths, preserving existing fields and making an initial backup.

Runtime packages live under `~/.local/share/dayz-asset-workbench` by default. Existing unmanaged dependency directories are preserved; choose a different `--runtime` if one already occupies that location. Blender's ordinary preferences and addon folders are not changed.

Connect both entries from the generated `.mcp.json` using your MCP client's configuration. For Codex CLI, this PowerShell snippet registers the entries through its supported MCP commands:

```powershell
$mcpConfig = Get-Content .mcp.json -Raw | ConvertFrom-Json
foreach ($entry in $mcpConfig.mcpServers.PSObject.Properties) {
    $mcpArgs = @('mcp', 'add', $entry.Name)
    foreach ($variable in $entry.Value.env.PSObject.Properties) {
        $mcpArgs += @('--env', "$($variable.Name)=$($variable.Value)")
    }
    $mcpArgs += @('--', $entry.Value.command) + $entry.Value.args
    & codex @mcpArgs
}
```

The repository also includes a Codex plugin manifest for local marketplace installation after setup. Use either the plugin or direct MCP registration to avoid duplicate tools. Start a new Codex thread after registering the tools. See [Codex MCP documentation](https://developers.openai.com/codex/mcp).

## Typical MCP session

1. Call `asset_status`, then `start_blender_session` with a project-relative `.blend` path. With no path, it uses `reports/preparation-latest.json` when available, otherwise starts a new scene. An already connected scene is preserved.
2. Inspect the scene and viewport. Use `import_asset` or `execute_blender_code` for scene work.
3. Call `export_active_p3d`; poll `get_asset_job` with its returned ID until completed or failed.
4. Inspect the output with `inspect_p3d`. Decode a PAA with `convert_texture(output_format="png")`, then call `get_asset_preview`.
5. Open the exported P3D or PAA in the native viewer when needed.

Conversions and exports create unique `<project>/work/mcp/<job-id>` directories. Logs, snapshots, results, and staged textures stay there. The source files and the live scene's geometry are preserved by export. Asset imports append objects. Raw Blender code can intentionally modify the scene, so save versions as you work.

## Export modes and limits

`visual_color` joins selected mesh names, or all meshes when none are specified, into one visual LOD. Each material must have a direct Base Color image node linked to Principled BSDF and an existing image file inside the project. Color images become `_co.paa`; the output uses a sanitized project-folder name as its virtual addon prefix. This is an interchange/preview export.

`configured_lods` exports authored Arma 3 Object Builder LOD objects and preserves their material/texture paths. Supply `texture_root` as the existing project directory representing the virtual drive root. Author LOD metadata, named selections, memory points, geometry, and materials through the Blender addon/API before using this mode.

P3D import/inspection supports **editable MLOD**, not binarized ODOL. Native viewer launch reports process launch only; it does not automate Object Builder's menus or verify its render. `ImageToPAA` encoding suffixes do not transform roughness/metallic maps into DayZ material channels. The tools do not generate game-ready item configuration, rigging, engine-specific LOD semantics, RVMATs, or PBO builds automatically. `game_ready` stays false until a separate in-game validation process establishes readiness.

The Blender bridge listens on `127.0.0.1` and enables local code execution. Use a trusted local MCP client. Telemetry is disabled in both the bridge environment and addon preferences; cloud asset-generation tools are excluded from the exposed tool list.

## Verification

Use the Python executable shown by the installer:

```powershell
& '<runtime>/venv/Scripts/python.exe' -m unittest discover -s tests -v
& '<runtime>/venv/Scripts/python.exe' tests/mcp_probe.py
& '<runtime>/venv/Scripts/python.exe' tests/mcp_probe.py --server blender
& '<runtime>/venv/Scripts/python.exe' tests/integration.py --open-viewers
```

The integration test requires a connected project scene with local Base Color image materials. It exports and reads back P3D, converts PAA to PNG and back, retrieves MCP images, imports and re-exports the P3D, removes the imported objects, and checks that the original object count remains unchanged. `--open-viewers` additionally launches the two native applications. All reports and images are gitignored.

Verified on 2026-09-13: eight regression tests; both servers' MCP initialization/tool discovery; live Blender scene/object/code/viewport operations; P3D export, inspection, import and configured-LOD round trip; PNG/PAA round trip; native viewer launch. The reference scene retained 5,864 vertices, 5,338 faces, and four texture references across the P3D round trip. This validates interchange, not in-game rendering.

See [THIRD_PARTY.md](THIRD_PARTY.md) for dependency provenance and licenses.
