import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Batch, Oven, Product
from app.services.oven_engine import (
    Interval,
    Occupancy,
    find_replan_conflicts,
)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    db = TestingSession()
    country = Product(name="乡村欧包", ferment_min=40, bake_min=35)
    brownie = Product(name="布朗尼", ferment_min=0, bake_min=30)
    oven1 = Oven(label="一层 1 号炉", capacity_note="盘炉")
    oven2 = Oven(label="一层 2 号炉", capacity_note="盘炉")
    db.add_all([country, brownie, oven1, oven2])
    db.flush()
    # 布朗尼 10:00 上 2 号炉，烘烤占 [600,630)
    db.add(Batch(product_id=brownie.id, oven_id=oven2.id, code="BO-1000", start_min=10 * 60))
    # 乡村欧包 10:40 上 2 号炉，发酵占 [640,680)，烘烤占 [680,715)
    db.add(Batch(product_id=country.id, oven_id=oven2.id, code="BO-1040", start_min=10 * 60 + 40))
    db.commit()
    ids = (brownie.id, country.id, oven1.id, oven2.id)
    db.close()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), ids
    app.dependency_overrides.clear()


def _gantt_bake_end(client, code):
    blocks = client.get("/api/gantt").json()
    return next(b["end_min"] for b in blocks if b["code"] == code and b["phase"] == "bake")


def test_extend_bake_overlap_reverts(client):
    c, (brownie_id, _, _, _) = client
    # 烘烤 30→45：布朗尼烘烤变 [600,645)，与 BO-1040 发酵 [640,680) 重叠
    r = c.put(f"/api/products/{brownie_id}", json={"ferment_min": 0, "bake_min": 45})
    assert r.status_code == 409
    # 产品页分钟退回改前
    brownie = next(p for p in c.get("/api/products").json() if p["id"] == brownie_id)
    assert brownie["bake_min"] == 30
    # 甘特色块长度不变
    assert _gantt_bake_end(c, "BO-1000") == 630
    # 冲突已记录
    logs = c.get("/api/conflicts").json()
    assert logs and "未生效" in logs[0]["detail"]


def test_extend_bake_no_overlap_applies(client):
    c, (brownie_id, _, _, _) = client
    # 烘烤 30→35：布朗尼烘烤变 [600,635)，不碰 BO-1040
    r = c.put(f"/api/products/{brownie_id}", json={"ferment_min": 0, "bake_min": 35})
    assert r.status_code == 200
    assert r.json()["bake_min"] == 35
    # 甘特色块随之变长
    assert _gantt_bake_end(c, "BO-1000") == 635
    # 批次烘烤止同步
    b = next(x for x in c.get("/api/batches").json() if x["code"] == "BO-1000")
    assert b["bake_end"] == 635


def test_shorter_bake_shrinks_blocks(client):
    c, (brownie_id, _, _, _) = client
    r = c.put(f"/api/products/{brownie_id}", json={"ferment_min": 0, "bake_min": 20})
    assert r.status_code == 200
    assert _gantt_bake_end(c, "BO-1000") == 620


def test_self_collision_between_same_product_batches(client):
    c, (brownie_id, _, oven1_id, _) = client
    # 空的一层 1 号炉放两个布朗尼：10:00 与 10:35，烘烤 [600,630)、[635,665)
    for start in (600, 635):
        r = c.post("/api/batches", json={"product_id": brownie_id, "oven_id": oven1_id, "start_min": start})
        assert r.status_code == 200
    # 烘烤 30→40：两批都按新时长重算为 [600,640)、[635,675)，彼此重叠
    r = c.put(f"/api/products/{brownie_id}", json={"ferment_min": 0, "bake_min": 40})
    assert r.status_code == 409
    brownie = next(p for p in c.get("/api/products").json() if p["id"] == brownie_id)
    assert brownie["bake_min"] == 30


def test_update_missing_product_404(client):
    c, _ = client
    r = c.put("/api/products/9999", json={"ferment_min": 0, "bake_min": 30})
    assert r.status_code == 404


def test_find_replan_conflicts_among_candidates():
    # 候选之间（同炉同产品两批次）互相重叠也要检出
    a = Occupancy(2, Interval(600, 640), "bake", 1)
    b = Occupancy(2, Interval(635, 675), "bake", 2)
    other_oven = Occupancy(1, Interval(600, 640), "bake", 3)
    assert find_replan_conflicts([], [a, b, other_oven])
    assert find_replan_conflicts([], [a, other_oven]) == []
