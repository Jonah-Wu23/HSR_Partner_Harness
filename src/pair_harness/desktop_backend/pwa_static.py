from __future__ import annotations

from pathlib import Path

from aiohttp import web


async def _not_found(request: web.Request) -> web.Response:
    return web.Response(status=404, text="Not Found")


def add_static_routes(app: web.Application, static_root: Path | None) -> None:
    """装配 PWA 静态路由。

    - static_root 为 None 时，GET / 及任意静态路径统一返回 404，如实报错、不合成页面；
    - static_root 非 None 时伺服该目录内的静态文件，目录列表关闭，路径穿越由
      aiohttp add_static 自带防护拒绝（不伺服目录外任何文件）。
    """
    if static_root is None:
        app.router.add_get("/", _not_found)
        app.router.add_get("/{tail:.*}", _not_found)
        return

    root = static_root

    async def index(request):
        """GET / 伺服 index.html；缺失时如实 404，不合成页面。"""
        index_file = root / "index.html"
        if index_file.is_file():
            return web.FileResponse(index_file)
        return _not_found(request)

    app.router.add_get("/", index)
    app.router.add_static("/", root, show_index=False)