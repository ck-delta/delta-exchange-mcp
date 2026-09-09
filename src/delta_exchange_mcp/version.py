"""The installed package version, as reported to Delta and to MCP clients."""

from importlib.metadata import PackageNotFoundError, version

try:
    PACKAGE_VERSION = version("delta-exchange-mcp")
except PackageNotFoundError:  # running from a source tree that was never installed
    PACKAGE_VERSION = "0+unknown"
