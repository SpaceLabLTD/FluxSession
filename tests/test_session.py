import unittest

from fluxsession import SessionManager, TDSession


class TestSessionManager(unittest.TestCase):
    def test_session_manager(self):
        session = TDSession(
            dc_id=1,
            api_id=123456,
            test_mode=True,
            auth_key=b"\x00" * 256,
            date=1234567890,
            user_id=1234567890,
            is_bot=False,
        )
        session_manager = SessionManager(session)
        self.assertEqual(len(session_manager.pyrogram_string_session(version=2)), 351)
