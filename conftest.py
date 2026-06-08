"""Root conftest: ensure project root is on sys.path for all test discovery."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
