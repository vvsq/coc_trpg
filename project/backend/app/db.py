"""数据库引擎与会话 — 全局唯一 engine，供 API 路由与脚本共用。"""
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# backend/data/coc.db（data 目录由 gitignore 或手动忽略，*.db 不入库）
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "coc.db"
DATA_DIR.mkdir(exist_ok=True)  # SQLite 不会自动建父目录，必须先建

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},  # SQLite + FastAPI 多线程必需
)


def init_db() -> None:
    """建全部表（create_all 只创建不存在的表，改字段后需删库重建）。"""
    # 在这里 import，确保所有 table=True 的类注册进 metadata 后再建表
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI 依赖：每个请求一个 Session。"""
    with Session(engine) as session:
        yield session
