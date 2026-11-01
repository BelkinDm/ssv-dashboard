"""Serve the panel files.

The panels open inside iframes on wall tablets that stay on for months, so the
files are sent with "no-cache": the browser asks every time and gets a 304 when
nothing changed. Each page also compares its own BUILD with the server every
10 minutes and reloads itself, and BUILD is stamped here with the integration
version — so after an update in HACS every panel picks up the new files by itself.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import STATIC_FILES, STATIC_URL

WWW = Path(__file__).parent / "www"
_BUILD_RE = re.compile(r"const BUILD = '[^']*';")
_TYPES = {".html": "text/html", ".js": "text/javascript"}


def _load(version: str) -> dict[str, tuple[bytes, str, str]]:
    out: dict[str, tuple[bytes, str, str]] = {}
    for name in STATIC_FILES:
        text = (WWW / name).read_text(encoding="utf-8")
        if name.endswith(".html"):
            # first occurrence only: the second one is the regex inside checkUpdate()
            text = _BUILD_RE.sub(f"const BUILD = '{version}';", text, count=1)
        else:
            text = text.replace("__SSV_VERSION__", version)
        body = text.encode("utf-8")
        etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
        out[name] = (body, _TYPES[Path(name).suffix], etag)
    return out


class SSVFilesView(HomeAssistantView):
    """GET /ssv_dashboard/<file>. No secrets inside, so no auth: iframes cannot send a token."""

    url = STATIC_URL + "/{filename}"
    name = "ssv_dashboard:files"
    requires_auth = False

    def __init__(self, files: dict[str, tuple[bytes, str, str]]) -> None:
        self._files = files

    async def get(self, request: web.Request, filename: str) -> web.Response:
        item = self._files.get(filename)
        if item is None:
            raise web.HTTPNotFound()
        body, ctype, etag = item
        headers = {"Cache-Control": "no-cache", "ETag": etag}
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        return web.Response(body=body, content_type=ctype, charset="utf-8", headers=headers)


async def async_register_files(hass: HomeAssistant, version: str) -> None:
    files = await hass.async_add_executor_job(_load, version)
    hass.http.register_view(SSVFilesView(files))
