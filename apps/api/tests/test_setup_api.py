"""配置引导 API（T-CFG-1 / T-SETUP-1 / T-SETUP-2 / T-SEC-6）。"""

from __future__ import annotations

from repolearn.core.security import decrypt_secret
from repolearn.models import LlmProfile, SettingRevision


async def test_setup_required_on_fresh_db(client):
    resp = await client.get("/v1/setup/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["required"] is True
    assert body["active_profile"] is None
    assert body["kernel"]["runtime"] in ("kernel", "exec", "template")


async def test_missing_internal_token_is_401(client):
    resp = await client.get("/v1/setup/state", headers={"X-Internal-Token": ""})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INTERNAL"


async def test_probe_failure_is_200_with_ok_false(client):
    """测量接口的唯一例外（P2-1）：失败是数据，不是异常。"""
    resp = await client.post(
        "/v1/setup/llm/probe",
        json={
            "provider": "openai",
            "protocol": "openai_chat",
            "api_key": "sk-invalid",
            "base_url": "http://127.0.0.1:9/v1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"]
    assert body["error"]["hint"]


async def test_commit_encrypts_key_and_writes_revision(client, session):
    resp = await client.post(
        "/v1/setup/commit",
        json={
            "llm": {
                "provider": "anthropic",
                "protocol": "anthropic_messages",
                "api_key": "sk-ant-secret-value-1234",
                "label": "主配置",
            },
            "roles": {"planner": "claude-sonnet-4-5", "writer": "claude-sonnet-4-5", "critic": "claude-sonnet-4-5"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["revision"] == 1
    assert body["profile_id"].startswith("prf_")

    profile = await session.get(LlmProfile, body["profile_id"])
    assert profile is not None
    assert profile.active is True
    # 密文里不能出现明文
    assert b"sk-ant-secret-value-1234" not in (profile.api_key_ciphertext or b"")
    assert decrypt_secret(profile.api_key_ciphertext, profile.id) == "sk-ant-secret-value-1234"
    assert profile.api_key_last4 == "1234"

    # 出站永不回传明文
    listed = await client.get("/v1/settings/profiles")
    payload = listed.json()
    assert "sk-ant-secret-value-1234" not in listed.text
    assert payload["items"][0]["api_key_last4"] == "1234"

    # revision payload 不含密文（P2-2）
    rows = (await session.execute(__import__("sqlalchemy").select(SettingRevision))).scalars().all()
    assert rows and "ciphertext" not in str(rows[0].payload)
    assert "sk-ant-secret-value-1234" not in str(rows[0].payload)


async def test_commit_requires_core_roles(client):
    resp = await client.post(
        "/v1/setup/commit",
        json={
            "llm": {"provider": "openai", "protocol": "openai_chat", "api_key": "sk-x"},
            "roles": {"planner": "", "writer": "", "critic": ""},
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "NO_MODEL_FOR_ROLE"


async def test_commit_without_csrf_is_403(client):
    """写操作必须带 CSRF（同源双提交）。"""
    resp = await client.post(
        "/v1/setup/commit",
        json={
            "llm": {"provider": "openai", "protocol": "openai_chat", "api_key": "sk-x"},
            "roles": {"planner": "gpt-4o", "writer": "gpt-4o", "critic": "gpt-4o"},
        },
        headers={"Cookie": "", "X-CSRF-Token": ""},
    )
    assert resp.status_code == 403


async def test_state_reflects_active_profile(client):
    await client.post(
        "/v1/setup/commit",
        json={
            "llm": {"provider": "openai", "protocol": "openai_chat", "api_key": "sk-x", "model_id": "gpt-4o"},
            "roles": {"planner": "gpt-4o", "writer": "gpt-4o", "critic": "gpt-4o"},
        },
    )
    resp = await client.get("/v1/setup/state")
    body = resp.json()
    assert body["required"] is False
    assert body["active_profile"]["provider"] == "openai"


async def test_rollback_creates_new_revision(client):
    await client.post(
        "/v1/setup/commit",
        json={
            "llm": {"provider": "openai", "protocol": "openai_chat", "api_key": "sk-x"},
            "roles": {"planner": "gpt-4o", "writer": "gpt-4o", "critic": "gpt-4o"},
        },
    )
    patched = await client.patch("/v1/settings/roles", json={"roles": {"writer": "gpt-4o-mini"}})
    assert patched.status_code == 200
    revision = patched.json()["revision"]
    assert revision == 2

    rolled = await client.post("/v1/settings/revisions/1/rollback")
    assert rolled.status_code == 200
    assert rolled.json()["revision"] >= 3

    state = await client.get("/v1/setup/state")
    assert state.json()["roles"]["writer"] == "gpt-4o"


async def test_revisions_list_is_descending(client):
    await client.post(
        "/v1/setup/commit",
        json={
            "llm": {"provider": "openai", "protocol": "openai_chat", "api_key": "sk-x"},
            "roles": {"planner": "gpt-4o", "writer": "gpt-4o", "critic": "gpt-4o"},
        },
    )
    resp = await client.get("/v1/settings/revisions")
    revs = [item["rev"] for item in resp.json()["items"]]
    assert revs == sorted(revs, reverse=True)


async def test_doctor_reports_checks(client):
    resp = await client.get("/v1/settings/doctor")
    assert resp.status_code == 200
    checks = resp.json()["checks"]
    names = {c["name"] for c in checks}
    assert "数据库" in names
    assert "Agent 内核" in names
    assert any(c["status"] in ("ok", "degraded") for c in checks)
