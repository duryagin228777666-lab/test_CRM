import pytest
from fastapi.testclient import TestClient

from app import leads
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        c.post("/login", data={"login": "demo", "password": "demo"})
        yield c


def test_requires_login():
    with TestClient(app) as anon:
        r = anon.get("/leads", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert anon.post("/login", data={"login": "demo", "password": "x"}).status_code == 401


def test_manual_lead_and_tags(client):
    r = client.post("/leads/new", follow_redirects=False, data={
        "name": "Тест Петров", "contact": "+79001234567",
        "request": "Нужно SEO", "tags": "SEO, #Горячий",
    })
    assert r.status_code == 303
    lead_id = int(r.headers["location"].rsplit("/", 1)[1])
    assert set(leads.get_lead(lead_id)["tags"]) == {"seo", "горячий", "вручную"}

    client.post(f"/leads/{lead_id}/tags", data={"tags": "vip"})
    client.post(f"/leads/{lead_id}/tags/remove", data={"tag": "горячий"})
    assert set(leads.get_lead(lead_id)["tags"]) == {"seo", "vip", "вручную"}
    assert "горячий" not in [t["name"] for t in leads.tag_counts()]

    by_tag = client.get("/leads", params={"tag": "seo"}).text
    assert "Тест Петров" in by_tag and "Ирина" not in by_tag
    assert "Тест Петров" in client.get("/leads", params={"q": "петров"}).text

    client.post(f"/leads/{lead_id}/status", data={"status": "in_work"})
    assert leads.get_lead(lead_id)["status"] == "in_work"
    assert client.get(f"/leads/{lead_id}").status_code == 200


def test_validation(client):
    assert client.post("/leads/new", data={"name": " ", "contact": ""}).status_code == 400
    assert client.get("/leads/999999").status_code == 404


def test_bot_source_tags():
    lead_id = leads.create_lead(
        name="Аня", contact="@anya", request="таргет", source="bot", tags=["таргет"],
        tg_user_id=1, tg_chat_id=1,
    )
    assert set(leads.get_lead(lead_id)["tags"]) == {"бот", "таргет"}
    assert leads.latest_lead_for_tg_user("bot", 1)["id"] == lead_id


def test_personal_telegram_flow():
    # Переписку начал менеджер: лида нет.
    assert leads.record_personal_message(chat_id=500, text="Привет", outgoing=True) == (None, False)

    lead_id, created = leads.record_personal_message(
        chat_id=501, text="Здравствуйте, нужна реклама", outgoing=False,
        sender_id=501, sender_name="Маша", sender_username="masha_shop",
    )
    assert created
    again, created = leads.record_personal_message(chat_id=501, text="Добрый день!", outgoing=True)
    assert again == lead_id and not created

    lead = leads.get_lead(lead_id)
    assert lead["tags"] == ["личный tg"] and lead["contact"] == "@masha_shop"
    assert [m["direction"] for m in lead["messages"]] == ["in", "out"]
