#!/usr/bin/env python3
"""
VIBESBOT - Click para iniciar
"""
import sys
import os

os.chdir("/workspace")
sys.path.insert(0, "/workspace")

from src.desktop_app import main
main()
