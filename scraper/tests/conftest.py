import sys
from pathlib import Path

# The scraper scripts import each other as top-level modules (run as
# `python scraper/<script>.py`), so make that directory importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
