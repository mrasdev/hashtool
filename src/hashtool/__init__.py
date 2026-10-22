"""Create SHA-256 manifests of directory trees and verify files against them."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hashtool")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"
