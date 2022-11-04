import base64
import ipaddress
import sqlite3
import struct
from enum import Enum
from os import getenv

from pydantic import BaseModel, Field
from telethon.sessions import StringSession
from telethon.sync import TelegramClient


class TDLib(Enum):
    PYROGRAM: str = "pyrogram"
    TELETHON: str = "telethon"


class TDSession(BaseModel):
    dc_id: int = Field(default=0)
    api_id: int = Field(default=0)
    test_mode: bool = Field(default=False)
    auth_key: bytes = Field(default=b"")
    date: int = Field(default=0)
    user_id: int = Field(default=0)
    is_bot: bool = Field(default=False)
    port: int = Field(default=443)

    @property
    def server_address(self):
        TEST_SERVER = {
            1: "149.154.175.10",
            2: "149.154.167.40",
            3: "149.154.175.117",
            121: "95.213.217.195",
        }
        PROD_SERVER = {
            1: "149.154.175.53",
            2: "149.154.167.51",
            3: "149.154.175.100",
            4: "149.154.167.91",
            5: "91.108.56.130",
            121: "95.213.217.195",
        }
        return ipaddress.ip_address(
            TEST_SERVER[self.dc_id] if self.test_mode else PROD_SERVER[self.dc_id]
        )


class SessionManager:
    def __init__(self, session: TDSession):
        self.session = session

    @classmethod
    def from_pyrogram_session_file(cls, file: str) -> "SessionManager":
        try:
            conn = sqlite3.connect(file, check_same_thread=False)
            version = conn.execute("SELECT number from version;").fetchone()[0]
            selected_session: tuple = conn.execute("SELECT * from sessions;").fetchone()
            conn.close()
        except sqlite3.DatabaseError:
            raise ValueError("Invalid Pyrogram session file")

        if version == 2:
            session = TDSession(
                dc_id=selected_session[0],
                test_mode=selected_session[1],
                auth_key=selected_session[2],
                date=selected_session[3],
                user_id=selected_session[4],
                is_bot=selected_session[5],
            )
            return cls(session)

        elif version == 3:
            session = TDSession(
                dc_id=selected_session[0],
                api_id=selected_session[1],
                test_mode=selected_session[2],
                auth_key=selected_session[3],
                date=selected_session[4],
                user_id=selected_session[5],
                is_bot=selected_session[6],
            )
            return cls(session)

        else:
            raise ValueError("Invalid version")

    @staticmethod
    def pyrogram_struct_formatter():
        return {351: ">B?256sI?", 356: ">B?256sQ?", 362: ">BI?256sQ?"}

    @classmethod
    def from_pyrogram_string_session(cls, session_string: str) -> "SessionManager":
        if len(session_string) in [351, 356]:
            api_id = 0
            dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
                cls.pyrogram_struct_formatter()[len(session_string)],
                base64.urlsafe_b64decode(session_string + "=" * (-len(session_string) % 4)),
            )

        elif len(session_string) == 362:
            dc_id, api_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
                cls.pyrogram_struct_formatter()[len(session_string)],
                base64.urlsafe_b64decode(session_string + "=" * (-len(session_string) % 4)),
            )

        else:
            raise ValueError("Invalid session string")

        session = TDSession(
            dc_id=dc_id,
            api_id=api_id,
            test_mode=test_mode,
            auth_key=auth_key,
            user_id=user_id,
            is_bot=is_bot,
        )
        return cls(session)

    @classmethod
    def from_telethon_string_session(
        cls,
        session_string: str,
        do_login: bool = False,
    ) -> "SessionManager":
        """Convert a Telethon string session to a TDLib session

        Args:
            session_string (str): Telethon string session
            do_login (bool, optional): If True then this token should not be used for other clients.
            Otherwise, auth token will be revoked. Defaults to False.

        Returns:
            SessionManager: SessionManager object
        """
        if session_string[0] == "1":
            session_string = session_string[1:]

        dc_id, _, port, auth_key = struct.unpack(
            ">B{}sH256s".format(4 if len(session_string) == 352 else 16),
            base64.urlsafe_b64decode(session_string + "=" * (-len(session_string) % 4)),
        )

        if do_login:
            client = TelegramClient(
                StringSession("1" + session_string),
                int(getenv("FLUX_SESSION_API_ID", 12345)),
                getenv("FLUX_SESSION_API_HASH", "0123456789abcdef0123456789abcdef"),
            )
            client.connect()
            if client.is_user_authorized():
                user = client.get_me()
                session = TDSession(
                    dc_id=dc_id,
                    test_mode=port == 80,
                    auth_key=auth_key,
                    user_id=user.id,
                    is_bot=user.bot,
                    port=port,
                )
                return cls(session)

        session = TDSession(
            dc_id=dc_id,
            test_mode=port == 80,
            auth_key=auth_key,
            port=port,
        )
        return cls(session)

    @classmethod
    def from_telethon_file(cls, file: str, do_login: bool = False) -> "SessionManager":
        try:
            conn = sqlite3.connect(file, check_same_thread=False)
            version = conn.execute("SELECT version from version;").fetchone()[0]
            authorization = conn.execute("SELECT * from sessions;").fetchone()
            conn.close()
        except sqlite3.DatabaseError:
            raise ValueError("Invalid Telethon session file")

        if version == 7:
            session = TDSession(
                dc_id=authorization[0],
                test_mode=authorization[2] == 80,
                auth_key=authorization[3],
                port=authorization[2],
            )
            cls_obj = cls(session)
            if do_login:
                string_session = cls_obj.telethon_string_session()
                client = TelegramClient(
                    StringSession(string_session),
                    int(getenv("FLUX_SESSION_API_ID", 12345)),
                    getenv("FLUX_SESSION_API_HASH", "0123456789abcdef0123456789abcdef"),
                )
                client.connect()
                if client.is_user_authorized():
                    user = client.get_me()
                    cls_obj.session.user_id = user.id
                    cls_obj.session.is_bot = user.bot
            return cls_obj

        else:
            raise ValueError("Invalid version")

    def pyrogram_string_session(self, version: int = 3, api_id: int = 0) -> str:
        """Export the session as a string.

        Args:
            version (int, optional): Allows user to specify the version of the string session.
            Defaults to 3.
            api_id (int, optional): Only used when version is 3. Defaults to 0.

        Raises:
            ValueError: If version is not 2 or 3.

        Returns:
            str: The string session.
        """

        if version == 2:
            if self.session.user_id > 2**32:
                return (
                    base64.urlsafe_b64encode(
                        struct.pack(
                            ">B?256sQ?",
                            self.session.dc_id,
                            self.session.test_mode,
                            self.session.auth_key,
                            self.session.user_id,
                            self.session.is_bot,
                        )
                    )
                    .decode()
                    .rstrip("=")
                )
            else:
                return (
                    base64.urlsafe_b64encode(
                        struct.pack(
                            ">B?256sI?",
                            self.session.dc_id,
                            self.session.test_mode,
                            self.session.auth_key,
                            self.session.user_id,
                            self.session.is_bot,
                        )
                    )
                    .decode()
                    .rstrip("=")
                )

        elif version == 3:
            return (
                base64.urlsafe_b64encode(
                    struct.pack(
                        ">BI?256sQ?",
                        self.session.dc_id,
                        api_id or self.session.api_id,
                        self.session.test_mode,
                        self.session.auth_key,
                        self.session.user_id,
                        self.session.is_bot,
                    )
                )
                .decode()
                .rstrip("=")
            )

        else:
            raise ValueError("Invalid version")

    def telethon_string_session(self):
        return "1" + base64.urlsafe_b64encode(
            struct.pack(
                ">B{}sH256s".format(len(self.session.server_address.packed)),
                self.session.dc_id,
                self.session.server_address.packed,
                self.session.port,
                self.session.auth_key,
            )
        ).decode("ascii")

    def telethon_file(self, file: str):
        conn = sqlite3.connect(file, check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS version (version INTEGER PRIMARY KEY);")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                    dc_id INTEGER PRIMARY KEY, 
                    server_address TEXT, 
                    port INTEGER, 
                    auth_key BLOB,
                    takeout_id INTEGER
                );
            """
        )
        conn.execute("INSERT INTO version VALUES (?);", (7,))
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?);",
            (
                self.session.dc_id,
                self.session.server_address.packed,
                self.session.port,
                self.session.auth_key,
                0,
            ),
        )
        conn.commit()
        conn.close()
        return file

    def pyrogram_file(self, file: str, **kwargs):
        conn = sqlite3.connect(file, check_same_thread=False)
        SCHEMA = """CREATE TABLE sessions
                    (
                        dc_id     INTEGER PRIMARY KEY,
                        api_id    INTEGER,
                        test_mode INTEGER,
                        auth_key  BLOB,
                        date      INTEGER NOT NULL,
                        user_id   INTEGER,
                        is_bot    INTEGER
                    );
                    CREATE TABLE peers
                    (
                        id             INTEGER PRIMARY KEY,
                        access_hash    INTEGER,
                        type           INTEGER NOT NULL,
                        username       TEXT,
                        phone_number   TEXT,
                        last_update_on INTEGER NOT NULL DEFAULT (CAST(STRFTIME('%s', 'now') AS INTEGER))
                    );
                    CREATE TABLE version
                    (
                        number INTEGER PRIMARY KEY
                    );
                    CREATE INDEX idx_peers_id ON peers (id);
                    CREATE INDEX idx_peers_username ON peers (username);
                    CREATE INDEX idx_peers_phone_number ON peers (phone_number);
                    CREATE TRIGGER trg_peers_last_update_on
                        AFTER UPDATE
                        ON peers
                    BEGIN
                        UPDATE peers
                        SET last_update_on = CAST(STRFTIME('%s', 'now') AS INTEGER)
                        WHERE id = NEW.id;
                    END;
        """
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO version VALUES (?)", (2,))
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (2, None, None, None, 0, None, None),
        )
        for k, v in {
            "dc_id": self.session.dc_id,
            "api_id": int(kwargs.get("api_id")) or self.session.api_id,
            "test_mode": self.session.test_mode,
            "auth_key": self.session.auth_key,
            "date": 0,
            "user_id": int(kwargs.get("user_id")) or self.session.user_id,
            "is_bot": bool(kwargs.get("is_bot")) or self.session.is_bot,
        }.items():
            conn.execute(f"UPDATE sessions SET {k} = ?", (v,))
        conn.commit()
        conn.close()
        return True
