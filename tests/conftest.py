"""pytest configuration — ensure PLATFORM env var is set before any import."""
import os

os.environ.setdefault('PLATFORM', 'gitee')
