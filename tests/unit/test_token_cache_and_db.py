from sqlalchemy import inspect

from authentication.token_manager import EncryptedTokenCache
from database.migrations.migrate import current_version, upgrade
from database.repository import make_engine


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_keyring(self):
        return self

    def get_password(self, s, u):
        return self.store.get((s, u))

    def set_password(self, s, u, p):
        self.store[(s, u)] = p


class FailKeyring(FakeKeyring):
    def get_password(self, s, u):
        raise RuntimeError("no backend")


def test_encrypted_cache_never_plaintext(tmp_path):
    kr = FakeKeyring()
    c = EncryptedTokenCache(tmp_path / "cache.bin", keyring_module=kr)
    assert c.enabled
    c.cache.add({"client_id": "cid", "scope": ["s"], "token_endpoint": "https://login.microsoftonline.com/t/oauth2/v2.0/token",
                 "response": {"access_token": "SECRET-ACCESS-TOKEN-VALUE", "expires_in": 3600, "token_type": "Bearer"}})
    c.save()
    raw = (tmp_path / "cache.bin").read_bytes()
    assert b"SECRET-ACCESS-TOKEN-VALUE" not in raw
    c2 = EncryptedTokenCache(tmp_path / "cache.bin", keyring_module=kr)
    assert "SECRET-ACCESS-TOKEN-VALUE" in c2.cache.serialize()


def test_no_secure_backend_disables_persistence(tmp_path):
    c = EncryptedTokenCache(tmp_path / "cache.bin", keyring_module=FailKeyring())
    assert not c.enabled
    c.save()
    assert not (tmp_path / "cache.bin").exists()


def test_migrations_idempotent(tmp_path):
    eng = make_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    assert current_version(eng) == 0
    assert upgrade(eng) == 1
    assert upgrade(eng) == 1
    tables = set(inspect(eng).get_table_names())
    assert {"comparison_sessions", "extracted_visuals", "extracted_visual_data", "mismatch_records", "audit_logs",
            "visual_mappings", "column_mappings", "screenshots", "mapping_profiles", "user_refs"} <= tables


def test_user_ref_hashes_account(repo):
    rid = repo.user_ref("Someone@Contoso.com")
    assert rid == repo.user_ref("someone@contoso.com")
    with repo.engine.connect() as conn:
        rows = conn.exec_driver_sql("select account_hash from user_refs").fetchall()
    assert "contoso" not in rows[0][0]
