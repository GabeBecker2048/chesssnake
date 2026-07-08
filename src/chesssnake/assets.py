"""Locate packaged data assets (piece images, fonts, SQL) at runtime.

Runtime assets live under ``chesssnake/data`` and are declared in
``pyproject.toml`` (``[tool.setuptools.package-data]``). Access them through
:func:`asset_path` rather than hard-coding ``importlib.resources`` calls.
"""

import importlib.resources


def asset_path(relpath: str) -> str:
    """
    Return the filesystem path to a packaged asset under ``chesssnake/data``.

    :param relpath: Path relative to the ``data`` directory, e.g.
        ``"img/template.png"`` or ``"init.sql"``.
    :type relpath: str
    :return: Absolute path to the asset as a string.
    :rtype: str
    """
    return str(importlib.resources.files("chesssnake").joinpath(f"data/{relpath}"))
