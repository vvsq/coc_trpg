"""卡牌 API 测试共享基建：tmp SQLite + TestClient + 种子职业灌库。

fixture 与 test_rooms_api.py 的本地定义同款（该文件保留自己的版本不受影响）；
卡牌类测试需要先有 occupation 表数据（create_card 从库里读职业），
seed_occupation 从 app/seed/occupations.json 按名取职业塞进临时库。
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401  确保全部 table=True 模型注册进 metadata
from app.db import get_session
from app.main import app
from app.models import OccupationRow
from app.rules.occupation import get_occupation


@pytest.fixture()
def test_engine(tmp_path):
    """每个测试一个独立临时库。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture()
def client(test_engine):
    """覆盖 get_session 后经 TestClient 走完整路由栈。"""

    def override():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def seed_occupation(test_engine):
    """把种子职业灌进临时库，返回按名灌库并取回 id 的函数。"""

    def _seed(*names: str) -> list[int]:
        picked = [get_occupation(name) for name in names]
        with Session(test_engine) as session:
            for occ in picked:
                session.add(OccupationRow(
                    id=occ.id,
                    name=occ.name,
                    era=occ.era,
                    data=occ.model_dump(mode='json'),
                ))
            session.commit()
        return [occ.id for occ in picked]

    return _seed
