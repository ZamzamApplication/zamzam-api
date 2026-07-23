import unittest
from datetime import datetime, timedelta

from app.models import TahfizInvitation, UserRole
from app.routers.invitations import invitation_status, invitation_token_hash


class InvitationTokenTests(unittest.TestCase):
    def test_raw_token_is_converted_to_fixed_hash(self):
        raw_token = "a-secret-single-use-token"
        hashed = invitation_token_hash(raw_token)

        self.assertNotEqual(hashed, raw_token)
        self.assertEqual(len(hashed), 64)
        self.assertEqual(hashed, invitation_token_hash(raw_token))


class InvitationStatusTests(unittest.TestCase):
    def make_invitation(self, **overrides) -> TahfizInvitation:
        values = {
            "id": 1,
            "tahfiz_id": 3,
            "token_hash": "a" * 64,
            "role": UserRole.sheikh,
            "created_by_id": 4,
            "created_at": datetime(2026, 7, 23, 10, 0),
            "expires_at": datetime(2026, 7, 25, 10, 0),
        }
        values.update(overrides)
        return TahfizInvitation(**values)

    def test_active_invitation_is_available_before_expiry(self):
        invitation = self.make_invitation()

        self.assertEqual(
            invitation_status(invitation, datetime(2026, 7, 24, 10, 0)),
            "active",
        )

    def test_used_status_takes_precedence(self):
        invitation = self.make_invitation(
            used_at=datetime(2026, 7, 23, 11, 0),
            revoked_at=datetime(2026, 7, 23, 12, 0),
        )

        self.assertEqual(invitation_status(invitation), "used")

    def test_expired_invitation_is_rejected(self):
        now = datetime(2026, 7, 25, 10, 1)
        invitation = self.make_invitation(expires_at=now - timedelta(minutes=1))

        self.assertEqual(invitation_status(invitation, now), "expired")


if __name__ == "__main__":
    unittest.main()
