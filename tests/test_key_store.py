import base64
from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import patch

from key_store import KeyStoreError, SupabaseKeyStore


class KeyStoreTest(TestCase):
    def test_encrypted_round_trip_and_delete(self):
        rows = {}
        secret = "sb_secret_fake_test_only"
        encryption_key = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
        store = SupabaseKeyStore("https://example.supabase.co", secret, encryption_key)

        def request(req, **kwargs):
            self.assertEqual(req.headers["Apikey"], secret)
            if req.get_method() == "POST":
                row = json.loads(req.data)
                rows[row["slot"]] = row
                return BytesIO(b"")
            if req.get_method() == "DELETE":
                rows.pop(req.full_url.split("eq.")[-1], None)
                return BytesIO(b"")
            return BytesIO(json.dumps(list(rows.values())).encode())

        with patch.object(store, "_open", side_effect=request):
            store.save("user", "PRIVATE_BAZE_KEY", {"gpt": ["gpt-test"]})
            self.assertNotIn("PRIVATE_BAZE_KEY", json.dumps(rows))
            self.assertEqual(store.load_all()["user"], ("PRIVATE_BAZE_KEY", {"gpt": ["gpt-test"]}))
            rows["user"]["payload"] = rows["user"]["payload"][:-2] + "AA"
            with self.assertRaises(KeyStoreError):
                store.load_all()
            store.delete("user")
            self.assertEqual(store.load_all(), {})

    def test_rejects_non_supabase_destination_before_secret_is_used(self):
        encryption_key = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
        with self.assertRaises(KeyStoreError):
            SupabaseKeyStore("https://attacker.example", "sb_secret_fake_test_only", encryption_key)
