# Dependencies

Our wrapper, installer, and tests are MIT-licensed. Dependencies retain their own licenses and are downloaded during installation; their source trees and binaries are not bundled in this repository.

| Component | Pin | License / source |
| --- | --- | --- |
| Blender MCP | `5f8ddaf6e987c4aa0c3467fcc548838b28f64477` | [MIT, ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp/blob/5f8ddaf6e987c4aa0c3467fcc548838b28f64477/LICENSE) |
| Arma 3 Object Builder | `2.5.1` | [GPL-3.0, MrClock8163/Arma3ObjectBuilder](https://github.com/MrClock8163/Arma3ObjectBuilder) |
| MCP Python SDK | `1.26.0` | [MIT, modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) |
| Blender | User-installed; tested with `3.5.0` | [Blender licensing](https://www.blender.org/about/license/) |
| DayZ Tools | User-installed | [Bohemia DayZ Tools](https://community.bistudio.com/wiki/DayZ:Tools) |

Archive URLs and SHA256 digests are in `dependencies.json`. Python runtime versions are in `requirements.lock.txt`. The Blender MCP build backend is resolved by pip during installation. This is a pinned runtime configuration, not a reproducible binary distribution.

Arma 3 Object Builder runs inside the Blender application for MLOD interchange; the MCP worker communicates with that process through job JSON files. No Bohemia executable, codec, game content, third-party mod content, or purchased model/texture is redistributed.
