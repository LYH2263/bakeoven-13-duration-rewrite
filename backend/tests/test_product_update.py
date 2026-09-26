"""产品配方修改：在排批次重算 + 重叠时整体退回的 API 验收测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Batch, Oven, Product

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    brownie = Product(name="布朗尼", ferment_min=0, bake_min=30)
    bread = Product(name="乡村欧包", ferment_min=40, bake_min=35)
    oven1 = Oven(label="一层 1 号炉", capacity_note="盘炉")
    oven2 = Oven(label="一层 2 号炉", capacity_note="盘炉")
    db.add_all([brownie, bread, oven1, oven2])
    db.flush()
    db.add_all(
        [
            # 一层 2 号炉：布朗尼 [600,630)，欧包发酵 [640,680) 烘烤 [680,715)
            Batch(product_id=brownie.id, oven_id=oven2.id, code="BO-1000", start_min=10 * 60),
            Batch(product_id=bread.id, oven_id=oven2.id, code="BO-1100", start_min=10 * 60 + 40),
        ]
    )
    db.commit()
    db.close()
    return TestClient(app)


def _product(client, name):
    return next(p for p in client.get("/api/products").json() if p["name"] == name)


def _batch(client, code):
    return next(b for b in client.get("/api/batches").json() if b["code"] == code)


def _block(client, code, phase):
    return next(
        b for b in client.get("/api/gantt").json()
        if b["code"] == code and b["phase"] == phase
    )


def test_extend_bake_conflict_reverts_to_old_minutes(client):
    """布朗尼烘烤 30→45 与一层 2 号炉下一批次重叠：修改不生效，分钟退回 30。"""
    pid = _product(client, "布朗尼")["id"]
    r = client.patch(f"/api/products/{pid}", json={"ferment_min": 0, "bake_min": 45})
    assert r.status_code == 409
    # 产品页分钟保持改前
    assert _product(client, "布朗尼")["bake_min"] == 30
    # 批次端点与甘特色块长度不变
    assert _batch(client, "BO-1000")["bake_end"] == 630
    bake = _block(client, "BO-1000", "bake")
    assert (bake["start_min"], bake["end_min"]) == (600, 630)
    # 冲突被记录
    assert any("BO-1000" in c["batch_code"] for c in client.get("/api/conflicts").json())


def test_extend_bake_without_conflict_reschedules(client):
    """无重叠：分钟生效，发酵止/烘烤止与甘特色块一起变长。"""
    pid = _product(client, "布朗尼")["id"]
    r = client.patch(f"/api/products/{pid}", json={"ferment_min": 0, "bake_min": 35})
    assert r.status_code == 200
    assert r.json()["rescheduled"] == 1
    assert _product(client, "布朗尼")["bake_min"] == 35
    b = _batch(client, "BO-1000")
    assert (b["ferment_end"], b["bake_end"]) == (600, 635)
    bake = _block(client, "BO-1000", "bake")
    assert (bake["start_min"], bake["end_min"]) == (600, 635)


def test_shorter_bake_shrinks_gantt_block(client):
    pid = _product(client, "布朗尼")["id"]
    r = client.patch(f"/api/products/{pid}", json={"ferment_min": 0, "bake_min": 20})
    assert r.status_code == 200
    assert _batch(client, "BO-1000")["bake_end"] == 620
    bake = _block(client, "BO-1000", "bake")
    assert (bake["start_min"], bake["end_min"]) == (600, 620)


def test_ferment_change_recacls_both_segments(client):
    pid = _product(client, "乡村欧包")["id"]
    r = client.patch(f"/api/products/{pid}", json={"ferment_min": 45, "bake_min": 35})
    assert r.status_code == 200
    b = _batch(client, "BO-1100")
    assert (b["ferment_end"], b["bake_end"]) == (685, 720)
    ferment = _block(client, "BO-1100", "ferment")
    bake = _block(client, "BO-1100", "bake")
    assert (ferment["start_min"], ferment["end_min"]) == (640, 685)
    assert (bake["start_min"], bake["end_min"]) == (685, 720)


def test_same_minutes_update_does_not_self_conflict(client):
    """分钟不变的保存也必须成功：被重算批次不与自己的旧占用冲突。"""
    pid = _product(client, "布朗尼")["id"]
    r = client.patch(f"/api/products/{pid}", json={"ferment_min": 0, "bake_min": 30})
    assert r.status_code == 200
    assert r.json()["rescheduled"] == 1


def test_update_missing_product_404(client):
    r = client.patch("/api/products/9999", json={"ferment_min": 0, "bake_min": 30})
    assert r.status_code == 404
