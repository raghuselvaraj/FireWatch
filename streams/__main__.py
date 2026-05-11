"""Entrypoint: ``python -m streams`` starts the fire-detection consumer."""
import sys
from pathlib import Path

# Make ``import config`` work when invoked from anywhere.
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from streams.stream import FireDetectionStream  # noqa: E402


def main() -> None:
    FireDetectionStream().run()


if __name__ == "__main__":
    main()
