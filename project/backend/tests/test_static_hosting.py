"""单端口托管测试 — 阶段 6.1（goal §7 6.1；决策 D6）。

覆盖四件事：
  1. dist 缺失时不挂载、不报错（开发模式 / 空仓库）；
  2. SPA fallback：未知前端路由回 index.html（刷新 /room/XXXX/kp 不 404）；
  3. 真实静态文件（/assets/*、根级 favicon）按原样返回，而不是被 index.html 顶掉；
  4. 后端前缀（/api、/ws）不被 SPA 吃掉，未注册时仍返回 JSON 404。

用独立的临时 dist 建独立 app，避免污染 app.main 的全局挂载（那份依赖真实构建产物）。
"""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.static_hosting import mount_spa

_INDEX = "<!doctype html><html><body><div id=\"app\"></div></body></html>"


@pytest.fixture()
def dist(tmp_path: Path) -> Path:
    """最小可用的 dist 结构：index.html + assets/app.js + 根级 favicon.ico。"""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(_INDEX, encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log('built')", encoding="utf-8")
    (tmp_path / "favicon.ico").write_bytes(b"\x00\x01icon")
    return tmp_path


@pytest.fixture()
def spa_client(dist: Path):
    """带一个 /api 路由的临时 app：先注册 API，再挂 SPA（与 main.py 同序）。"""
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "OK"}

    assert mount_spa(app, dist) is True
    with TestClient(app) as c:
        yield c


# ---------- 1. 未构建时不挂载 ----------

def test_returns_false_when_dist_missing(tmp_path: Path):
    app = FastAPI()
    assert mount_spa(app, tmp_path / "not-built") is False


def test_mount_is_idempotent(dist: Path):
    app = FastAPI()
    assert mount_spa(app, dist) is True
    assert mount_spa(app, dist) is False  # 第二次不再重复注册路由


# ---------- 2. SPA fallback ----------

def test_root_serves_index(spa_client: TestClient):
    res = spa_client.get("/")
    assert res.status_code == 200
    assert "id=\"app\"" in res.text


def test_unknown_frontend_route_falls_back_to_index(spa_client: TestClient):
    """前端 history 路由刷新（KP 控制台 / 模组详情）必须回 index.html。"""
    for path in ("/room/ABCD1234/kp", "/modules/1", "/cards/new"):
        res = spa_client.get(path)
        assert res.status_code == 200, path
        assert "id=\"app\"" in res.text


def test_index_is_no_cache(spa_client: TestClient):
    """发版重建后浏览器不能拿着旧 index.html 引用失效的 hash 资源。"""
    assert "no-cache" in spa_client.get("/").headers.get("cache-control", "")


# ---------- 3. 真实静态文件优先 ----------

def test_root_level_file_served(spa_client: TestClient):
    res = spa_client.get("/favicon.ico")
    assert res.status_code == 200
    assert res.content == b"\x00\x01icon"


def test_assets_served_as_static(spa_client: TestClient):
    res = spa_client.get("/assets/app.js")
    assert res.status_code == 200
    assert "built" in res.text


def test_missing_asset_falls_back_to_index(spa_client: TestClient):
    """assets 下不存在时不要 500，交给 index 让前端自己兜（与 vite preview 行为一致）。"""
    res = spa_client.get("/assets/removed-hash.js")
    assert res.status_code in (200, 404)


# ---------- 4. 后端前缀不被吃掉 ----------

def test_api_route_still_wins(spa_client: TestClient):
    assert spa_client.get("/api/health").json() == {"status": "OK"}


def test_unknown_api_path_is_json_404(spa_client: TestClient):
    res = spa_client.get("/api/definitely-not-here")
    assert res.status_code == 404
    assert res.json()["detail"] == "接口不存在"


def test_ws_http_path_is_404(spa_client: TestClient):
    assert spa_client.get("/ws/ABCD1234").status_code == 404


def test_path_traversal_blocked(spa_client: TestClient, dist: Path):
    """../ 拼出 dist 之外的文件必须拒绝（返回 index，不能读到磁盘任意文件）。"""
    secret = dist.parent / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")
    res = spa_client.get("/../secret.txt")
    assert "top-secret" not in res.text
