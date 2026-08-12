"""SDLC — AI-powered development lifecycle orchestration."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("sdlc")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
