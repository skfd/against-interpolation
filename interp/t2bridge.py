"""Bridge to the address-importer-friend engine's `t2` package.

We reuse its read-only Toronto address DB access and street normalizer rather
than re-deriving either. The engine is city-generic: `t2.config` reads
T2_CITY_DIR to find the city checkout (toronto-2-address-import) whose
config.toml supplies the source SQLite path. So we arrange two things before
importing: the engine root on sys.path, and T2_CITY_DIR pointed at Toronto.
"""
import os
import sys

from .config import load

_cfg = load()
if _cfg.t2_root not in sys.path:
    sys.path.insert(0, _cfg.t2_root)
os.environ.setdefault("T2_CITY_DIR", _cfg.t2_city_dir)

from t2 import source_db  # noqa: E402
from t2 import conflate  # noqa: E402

normalize_street = conflate.normalize_street
