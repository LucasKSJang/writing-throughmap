"""Test package. Puts the throughmap scripts folder first on sys.path."""

import pathlib
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "skills" / "throughmap" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
