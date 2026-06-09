"""Bridge to the sibling toronto-2-address-import project's `t2` package.

We reuse its read-only Toronto address DB access and street normalizer rather
than re-deriving either. Importing `t2.config` self-loads that project's own
config.toml (for the source SQLite path), so the only thing we have to arrange
is putting its root on sys.path.
"""
import sys

from .config import load

_cfg = load()
if _cfg.t2_root not in sys.path:
    sys.path.insert(0, _cfg.t2_root)

from t2 import source_db  # noqa: E402
from t2 import conflate  # noqa: E402

normalize_street = conflate.normalize_street
