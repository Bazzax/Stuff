import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The project directory has a hyphen in its name, so it is not importable as
# a package; put it (for `reviewer`) and this folder (for helpers) on the path.
for path in (HERE.parent, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
