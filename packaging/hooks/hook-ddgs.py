"""Bundle DDGS's dynamically discovered engines and native HTTP transport."""

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = collect_all("primp")
hiddenimports += ["ddgs.ddgs", *collect_submodules("ddgs.engines")]
# The desktop app uses direct public search, without DDGS's optional servers.
excludedimports = ["ddgs.dht", "ddgs.api_server", "ddgs.cli", "ddgs.mcp"]
