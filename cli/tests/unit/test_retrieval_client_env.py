from cli.commands.repair_utils import child_env


def test_child_env_drops_the_clis_secrets(monkeypatch):
    for name in ["CLIENT_PRIVATE_KEY", "SP_PRIVATE_KEY", "ADMIN_PRIVATE_KEY", "FILPAY_PRIVATE_KEY", "SP_LOTUS_TOKEN", "SP_REGISTRY_DATABASE_URL"]:
        monkeypatch.setenv(name, "placeholder-secret")
    monkeypatch.setenv("RPC_URL", "https://example.com")

    env = child_env(EXTRA="1")

    assert "placeholder-secret" not in env.values()
    assert env["RPC_URL"] == "https://example.com" and env["EXTRA"] == "1"
    assert child_env(keep=("FILPAY_PRIVATE_KEY",))["FILPAY_PRIVATE_KEY"] == "placeholder-secret"
