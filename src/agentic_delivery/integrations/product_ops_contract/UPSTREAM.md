# Public contract provenance

Vendored from Agentic Product Ops `main`, commit `a154945075505cff44f0cf3471d72d55d7b5101f`,
under the adjacent MIT LICENSE. That commit includes the read-back fix for Linear's
HTML-entity decoding (PER-16). `verifier.py`, `documentation.py` and the schema are unchanged
from the earlier pin `f04d8453`. No producer persistence or internal service modules are
vendored.

Hashes below use committed Git blobs (LF), independent of checkout line-ending settings.

| File | SHA-256 |
| --- | --- |
| verifier.py | `5dac9470140a4ba21b540252fe2e0982ce80ab72649488467f856701608d629b` |
| documentation.py | `54bbeebda03640bbd73616bb747718b3a958c84329fb287f5eb3a92d60f5b3e5` |
| linear_markdown.py | `3c73101b271657d516f1cc4951e426357b73ba803bdb950f41f08d94e22645b4` |
| handoff-v2.schema.json | `9f8b1de045c3b018ca9844e5f38015004d91b4db263c7f8f96f148642e226bf8` |

Update the upstream pin, hashes, producer/consumer contract tests and wheel smoke together.
Markdown parser versions are pinned identically in both projects.
