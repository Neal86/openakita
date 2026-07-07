from fastapi import FastAPI
from fastapi.testclient import TestClient

from openakita.api.routes.sessions import router
from openakita.sessions import SessionManager


def _stale_todo() -> dict:
    return {
        "id": "plan_703",
        "taskSummary": "卸载 thirdparty 备份软件并清理残留",
        "status": "in_progress",
        "steps": [
            {"id": "step_1", "description": "停止服务", "status": "in_progress"},
            {"id": "step_2", "description": "卸载程序", "status": "pending"},
        ],
    }


def _client_with_session(tmp_path, message_count: int = 120) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    session = manager.get_session("desktop", "conv1", "desktop_user")
    for i in range(message_count):
        role = "user" if i % 2 == 0 else "assistant"
        session.add_message(role, f"msg-{i}")
    app.state.session_manager = manager
    return TestClient(app)


def test_history_defaults_to_recent_window(tmp_path):
    client = _client_with_session(tmp_path, 120)

    resp = client.get("/api/sessions/conv1/history")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 120
    assert len(body["messages"]) == 80
    assert body["messages"][0]["content"] == "msg-40"
    assert body["messages"][-1]["content"] == "msg-119"
    assert body["start_index"] == 40
    assert body["end_index"] == 119
    assert body["has_more_before"] is True


def test_history_can_page_before_stable_index(tmp_path):
    client = _client_with_session(tmp_path, 120)

    resp = client.get("/api/sessions/conv1/history", params={"limit": 30, "before": 40})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 120
    assert len(body["messages"]) == 30
    assert body["messages"][0]["content"] == "msg-10"
    assert body["messages"][-1]["content"] == "msg-39"
    assert body["start_index"] == 10
    assert body["end_index"] == 39
    assert body["has_more_before"] is True


def test_history_strips_non_ui_system_summaries(tmp_path):
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    session = manager.get_session("desktop", "conv1", "desktop_user")
    session.add_message("system", "[历史背景，非当前任务] very large summary")
    session.add_message("user", "visible")
    app.state.session_manager = manager

    body = TestClient(app).get("/api/sessions/conv1/history").json()

    assert body["total"] == 1
    assert [m["content"] for m in body["messages"]] == ["visible"]


def test_history_filters_near_duplicate_user_messages(tmp_path):
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    session = manager.get_session("desktop", "conv1", "desktop_user")
    session.context.messages = [
        {"role": "user", "content": "same prompt", "timestamp": "2026-06-25T18:06:53.993669"},
        {"role": "user", "content": "same prompt", "timestamp": "2026-06-25T18:06:53.999736"},
        {"role": "assistant", "content": "done", "timestamp": "2026-06-25T18:07:00"},
    ]
    app.state.session_manager = manager

    body = TestClient(app).get("/api/sessions/conv1/history").json()

    assert body["total"] == 2
    assert [m["content"] for m in body["messages"]] == ["same prompt", "done"]


def test_history_backfill_skips_near_duplicate_turns(tmp_path):
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    session = manager.get_session("desktop", "conv1", "desktop_user")
    session.context.messages = [
        {"role": "user", "content": "same prompt", "timestamp": "2026-06-25T18:06:53.993669"},
    ]
    manager.set_turn_loader(
        lambda _safe_id: [
            {
                "role": "user",
                "content": "same prompt",
                "timestamp": "2026-06-25T18:06:53.999736",
            },
            {"role": "assistant", "content": "done", "timestamp": "2026-06-25T18:07:00"},
        ]
    )
    app.state.session_manager = manager

    body = TestClient(app).get("/api/sessions/conv1/history").json()

    assert body["total"] == 2
    assert [m["content"] for m in body["messages"]] == ["same prompt", "done"]
    assert [m["content"] for m in session.context.messages].count("same prompt") == 1


def test_history_reconciles_later_completion_only_todo_event(tmp_path):
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    session = manager.get_session("desktop", "conv1", "desktop_user")
    stale = _stale_todo()
    session.add_message("user", "卸载 thirdparty")
    session.add_message(
        "assistant",
        "开始计划",
        todo=stale,
        progress_events=[
            {"type": "todo_created", "plan": stale},
            {"type": "todo_step_updated", "stepId": "step_1", "status": "in_progress"},
        ],
    )
    session.add_message("user", "这是工作软件，不要卸载")
    session.add_message(
        "assistant",
        "计划已关闭",
        progress_events=[
            {"type": "todo_completed"},
            {
                "type": "todo_step_updated",
                "stepId": "step_1",
                "status": "completed",
                "result": "已取消",
            },
            {
                "type": "todo_step_updated",
                "stepId": "step_2",
                "status": "completed",
                "result": "已取消",
            },
        ],
    )
    app.state.session_manager = manager

    body = TestClient(app).get("/api/sessions/conv1/history").json()
    created = next(m for m in body["messages"] if m["content"] == "开始计划")
    plan_part = next(p for p in created["parts"] if p["kind"] == "plan")

    assert created["todo"]["status"] == "completed"
    assert [step["status"] for step in created["todo"]["steps"]] == ["completed", "completed"]
    assert plan_part["todo"]["status"] == "completed"
    assert body["active_todo"] is None


def test_session_list_returns_conversation_ui_state(tmp_path):
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    session = manager.get_session("desktop", "conv1", "desktop_user")
    session.add_message("user", "hello")
    session.set_metadata("selected_endpoint", "deepseek")
    session.set_metadata(
        "ui_org_state",
        {"orgMode": True, "orgId": "org_company", "orgNodeId": "pm"},
    )
    app.state.session_manager = manager

    body = TestClient(app).get("/api/sessions").json()

    assert body["sessions"][0]["endpointId"] == "deepseek"
    assert body["sessions"][0]["orgMode"] is True
    assert body["sessions"][0]["orgId"] == "org_company"
    assert body["sessions"][0]["orgNodeId"] == "pm"


def test_update_session_ui_state_persists_conversation_selection(tmp_path):
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    session = manager.get_session("desktop", "conv1", "desktop_user")
    session.add_message("user", "hello")
    app.state.session_manager = manager

    resp = TestClient(app).post(
        "/api/sessions/conv1/ui-state",
        json={
            "endpointId": "minimax",
            "orgMode": True,
            "orgId": "org_ops",
            "orgNodeId": None,
        },
    )

    assert resp.status_code == 200
    assert session.get_metadata("selected_endpoint") == "minimax"
    assert session.get_metadata("ui_org_state") == {
        "orgMode": True,
        "orgId": "org_ops",
        "orgNodeId": "",
    }


def test_update_session_ui_state_does_not_create_empty_session(tmp_path):
    app = FastAPI()
    app.include_router(router)
    manager = SessionManager(storage_path=tmp_path)
    app.state.session_manager = manager

    resp = TestClient(app).post(
        "/api/sessions/missing/ui-state",
        json={"endpointId": "minimax", "orgMode": False},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "reason": "session_not_found"}
    assert (
        manager.get_session("desktop", "missing", "desktop_user", create_if_missing=False) is None
    )
