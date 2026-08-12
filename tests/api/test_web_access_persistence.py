import json
import threading
from pathlib import Path

from openakita.api.auth import WebAccessConfig


def test_web_access_recovers_password_from_backup(tmp_path: Path):
    config = WebAccessConfig(tmp_path)
    config.change_password("first-password")
    config.change_password("second-password")
    path = tmp_path / "web_access.json"
    backup = path.with_suffix(".json.bak")
    assert backup.exists()
    path.write_text("{broken", "utf-8")

    recovered = WebAccessConfig(tmp_path)
    assert recovered.verify_password("first-password")
    assert json.loads(path.read_text("utf-8"))["password_user_set"] is True


def test_two_config_instances_do_not_lose_token_version_updates(tmp_path: Path):
    first = WebAccessConfig(tmp_path)
    second = WebAccessConfig(tmp_path)
    initial = first.token_version
    barrier = threading.Barrier(2)

    def mutate(config: WebAccessConfig, password: str) -> None:
        barrier.wait()
        config.change_password(password)

    a = threading.Thread(target=mutate, args=(first, "password-a"))
    b = threading.Thread(target=mutate, args=(second, "password-b"))
    a.start()
    b.start()
    a.join()
    b.join()

    final = WebAccessConfig(tmp_path)
    assert final.token_version == initial + 2
    assert final.verify_password("password-a") or final.verify_password("password-b")


def test_atomic_io_leaves_no_fixed_tmp_file(tmp_path: Path):
    config = WebAccessConfig(tmp_path)
    config.change_password("password")
    assert not (tmp_path / "web_access.tmp").exists()
    assert not (tmp_path / "web_access.json.tmp").exists()


def test_running_config_observes_external_password_reset(tmp_path: Path):
    server = WebAccessConfig(tmp_path)
    server.change_password("server-password")
    access_token = server.create_access_token()

    cli = WebAccessConfig(tmp_path)
    cli.clear_password()

    assert not server.has_password_set
    assert not server.verify_password("server-password")
    assert not server.validate_access_token(access_token)


def test_running_config_observes_external_password_change(tmp_path: Path):
    server = WebAccessConfig(tmp_path)
    server.change_password("old-password")

    other = WebAccessConfig(tmp_path)
    other.change_password("new-password")

    assert server.verify_password("new-password")
    assert not server.verify_password("old-password")
