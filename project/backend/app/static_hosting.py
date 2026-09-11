"""单端口托管 — 阶段 6.1（goal §7 6.1；决策 D6）。

把前端 `npm run build` 产物（`project/frontend/dist`）挂到 FastAPI 根路径，
让局域网用户只需访问一个地址（`http://<IP>:8000`），不必再起 Vite 5173。

约定：
  - `/api/*`、`/ws/*`、`/docs`、`/openapi.json` 由先注册的路由优先匹配，不受影响；
  - `/assets/*` 交给 StaticFiles（带 ETag / Last-Modified，可直接长缓存）；
  - 其余路径先找 dist 下的真实文件（favicon.ico / vite.svg 等），找不到就回 `index.html`
    —— 这是 SPA 前端路由（`/room/XXXX/kp`、`/modules/1`）刷新不 404 的关键；
  - `index.html` 带 `Cache-Control: no-cache`：每次发版重建后浏览器立刻拿到新版本，
    不会再引用上一版已失效的 hash 资源。

开发模式（`npm run dev`）仍走 Vite 代理，dist 不存在时本模块静默跳过，
因此 `pytest` / 首次建库前的空仓库都不会被拖挂。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# project/backend/app/static_hosting.py -> parents[2] = project/
DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# 这些前缀由后端自己负责，命中未注册的路径时应报 404，而不是被 SPA 回退吃掉
# （否则前端拿到的是一份 HTML，axios 解析 detail 会得到莫名其妙的错误）
_SERVER_PREFIXES = ("api/", "ws/")


def mount_spa(app: FastAPI, dist_dir: Path = DIST_DIR) -> bool:
    """把 dist 挂到 app 根路径；返回是否挂载成功（dist 缺失或已挂过为 False）。

    幂等：同一个 app 重复调用只生效一次（测试里给临时 dist 建独立 app，见
    tests/test_static_hosting.py）。
    """
    dist_dir = Path(dist_dir)
    index_file = dist_dir / "index.html"
    if not index_file.is_file():
        return False
    if getattr(app.state, "spa_mounted", False):
        return False

    app.state.spa_mounted = True
    app.state.spa_dist_dir = dist_dir
    dist_root = dist_dir.resolve()

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith(_SERVER_PREFIXES):
            raise HTTPException(status_code=404, detail="接口不存在")
        if full_path:
            target = (dist_dir / full_path).resolve()
            # 防目录穿越：拼出来的路径必须仍在 dist 内
            if target.is_relative_to(dist_root) and target.is_file():
                return FileResponse(target)
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})

    return True
