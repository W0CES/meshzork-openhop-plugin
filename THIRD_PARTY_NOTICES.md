# Third-party notices

`meshzork_plugin/meshcore_client.py` is an adaptation of the Companion transport
pattern in `openhop-dev/openhop-nomad-plugin`, which is distributed under the MIT
License. The adapted file is intentionally kept small and uses protocol constants
from the `openhop-core` package at runtime.

- Source: <https://github.com/openhop-dev/openhop-nomad-plugin>
- License: <https://github.com/openhop-dev/openhop-nomad-plugin/blob/main/LICENSE>

`meshzork_plugin/assets/zork1.z3` is the compiled Z-machine program published as
`zork1.zip` in Microsoft's Historical Source repository for Zork I. That
repository is distributed under the MIT License, Copyright (c) 2025 Microsoft.
The filename uses the modern `.z3` extension to make clear that it is a version
3 Z-machine program, not a PKZIP archive.

- Source: <https://github.com/historicalsource/zork1>
- Source revision: `97b7b3d68c075dd9af7da499c3e9690ada3471fd`
- License: <https://github.com/historicalsource/zork1/blob/master/LICENSE>

`meshzork_plugin/assets/meshzork-openhop.png` is project artwork supplied by the
author for MeshZork branding. It is included in the wheel and shown in the
project README; it is not used as an openHop manifest field because schema 1 has
no declared icon property.

MeshZork runs the story through `yazm-py`, a pure-Python Z-machine version 3
interpreter distributed under the MIT License. It is installed as the pinned
Python dependency `yazm-py==0.2.0` in MeshZork's isolated plugin environment.

- Source: <https://github.com/swilcox/yazm-py>
- License: <https://github.com/swilcox/yazm-py/blob/master/LICENSE>
