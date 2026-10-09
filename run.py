import os
import sys

from interp.config import CITY_ENV


def _city_from_argv(argv: list[str]) -> str:
    """`--city X` / `--city=X`, read before anything imports the engine.

    `interp.cli` imports `coverage`, which imports `t2bridge`, which binds the
    t2 engine to one city checkout at import time. So the city has to be in
    the environment before `interp.cli` is imported, not merely before
    `main()` runs. (The first Guelph build got Toronto's 523,731 points.)
    """
    for i, arg in enumerate(argv):
        if arg == "--city" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--city="):
            return arg.split("=", 1)[1]
    return "toronto"


os.environ[CITY_ENV] = _city_from_argv(sys.argv[1:])

from interp.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
