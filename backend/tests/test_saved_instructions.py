"""The team's saved instructions for the AI: CRUD, team scope, plan gating and limits."""
import pytest

from app.models.saved_instruction import SavedInstruction

STYLE = "Use British spelling. Keep company names in Italian."


def _create(client, owner, name="Client Rossi – style", text=STYLE):
    return client.post("/instructions", headers=owner["headers"], json={"name": name, "text": text})


def test_crud(client, db, make_user):
    owner = make_user(plan="BASIC")
    h = owner["headers"]
    r = _create(client, owner, name="  Client  Rossi – style ", text=f"  {STYLE}\n")
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["name"] == "Client Rossi – style" and item["text"] == STYLE
    _create(client, owner, name="UK immigration (UKVI)", text="Dates as DD Month YYYY")
    assert [i["name"] for i in client.get("/instructions", headers=h).json()["items"]] == [
        "Client Rossi – style", "UK immigration (UKVI)",
    ]

    r = client.patch(f"/instructions/{item['id']}", headers=h, json={"name": "Rossi"})
    assert r.status_code == 200 and r.json()["name"] == "Rossi" and r.json()["text"] == STYLE
    r = client.patch(f"/instructions/{item['id']}", headers=h, json={"text": "Formal register"})
    assert r.json()["text"] == "Formal register" and r.json()["name"] == "Rossi"

    assert client.delete(f"/instructions/{item['id']}", headers=h).status_code == 200
    assert [i["name"] for i in client.get("/instructions", headers=h).json()["items"]] == ["UK immigration (UKVI)"]
    assert client.delete(f"/instructions/{item['id']}", headers=h).status_code == 404
    row = db.query(SavedInstruction).one()
    assert row.created_by == owner["user"].id and row.team_id == owner["team"].id


def test_members_share_the_team_library(client, make_user):
    owner = make_user(plan="PRO")
    member = make_user(team=owner["team"])
    item = _create(client, owner).json()
    assert [i["id"] for i in client.get("/instructions", headers=member["headers"]).json()["items"]] == [item["id"]]
    assert client.patch(f"/instructions/{item['id']}", headers=member["headers"], json={"name": "Rossi"}).status_code == 200


def test_other_teams_cant_see_or_change(client, db, make_user):
    owner, other = make_user(plan="PRO"), make_user(plan="PRO")
    item = _create(client, owner).json()
    assert client.get("/instructions", headers=other["headers"]).json()["items"] == []
    assert client.patch(f"/instructions/{item['id']}", headers=other["headers"], json={"name": "x"}).status_code == 404
    assert client.delete(f"/instructions/{item['id']}", headers=other["headers"]).status_code == 404
    # The same name is free in another team.
    assert _create(client, other).status_code == 201
    assert db.query(SavedInstruction).count() == 2


@pytest.mark.parametrize("expired", [False, True])
def test_trial_is_refused(client, db, make_user, expired):
    trial = make_user(plan="TRIAL", expires_in_days=-1 if expired else 7)
    pro = make_user(plan="PRO")
    item = _create(client, pro).json()
    h = trial["headers"]
    assert client.get("/instructions", headers=h).status_code == 403
    assert _create(client, trial).status_code == 403
    assert client.patch(f"/instructions/{item['id']}", headers=h, json={"name": "x"}).status_code == 403
    assert client.delete(f"/instructions/{item['id']}", headers=h).status_code == 403
    assert db.query(SavedInstruction).count() == 1


def test_length_limits(client, db, make_user):
    owner = make_user(plan="BASIC")
    assert _create(client, owner, name="n" * 81).status_code == 422
    assert _create(client, owner, name="   ").status_code == 422
    assert _create(client, owner, text="x" * 1001).status_code == 422
    assert _create(client, owner, text="  \n ").status_code == 422
    assert db.query(SavedInstruction).count() == 0
    item = _create(client, owner, name="n" * 80, text="  " + "x" * 1000 + "  ").json()
    assert len(item["text"]) == 1000
    h = owner["headers"]
    assert client.patch(f"/instructions/{item['id']}", headers=h, json={"text": "y" * 1001}).status_code == 422
    assert client.patch(f"/instructions/{item['id']}", headers=h, json={"name": ""}).status_code == 422


def test_duplicate_names_ignore_case(client, db, make_user):
    owner = make_user(plan="PRO")
    first = _create(client, owner, name="UKVI").json()
    second = _create(client, owner, name="Rossi").json()
    assert _create(client, owner, name="ukvi").status_code == 409
    h = owner["headers"]
    assert client.patch(f"/instructions/{second['id']}", headers=h, json={"name": "UKvi"}).status_code == 409
    # Renaming to its own name in another case is fine.
    assert client.patch(f"/instructions/{first['id']}", headers=h, json={"name": "ukvi"}).json()["name"] == "ukvi"
    assert db.query(SavedInstruction).count() == 2
