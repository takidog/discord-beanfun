import os
import secrets
import time
from typing import Optional

import aiosqlite

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS api_tokens (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    token            TEXT    UNIQUE NOT NULL,
    app_name         TEXT    NOT NULL,
    channel_id       INTEGER NOT NULL,
    channel_name     TEXT,
    discord_user_id  INTEGER NOT NULL,
    discord_username TEXT,
    created_at       REAL    NOT NULL,
    expires_at       REAL,
    revoked          INTEGER DEFAULT 0,
    revoked_at       REAL
);
"""


class TokenRecord:
    """Lightweight wrapper around a row from api_tokens."""

    __slots__ = (
        "id",
        "token",
        "app_name",
        "channel_id",
        "channel_name",
        "discord_user_id",
        "discord_username",
        "created_at",
        "expires_at",
        "revoked",
        "revoked_at",
    )

    def __init__(self, row: aiosqlite.Row):
        (
            self.id,
            self.token,
            self.app_name,
            self.channel_id,
            self.channel_name,
            self.discord_user_id,
            self.discord_username,
            self.created_at,
            self.expires_at,
            self.revoked,
            self.revoked_at,
        ) = row


class TokenDatabase:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE_SQL)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def create_token(
        self,
        app_name: str,
        channel_id: int,
        channel_name: str,
        discord_user_id: int,
        discord_username: str,
        expires_in_seconds: Optional[int] = None,
    ) -> str:
        """Create a new API token. Returns the raw token string."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = None
        if expires_in_seconds is not None and expires_in_seconds > 0:
            expires_at = now + expires_in_seconds

        await self._db.execute(
            """
            INSERT INTO api_tokens
                (token, app_name, channel_id, channel_name,
                 discord_user_id, discord_username, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                app_name,
                channel_id,
                channel_name,
                discord_user_id,
                discord_username,
                now,
                expires_at,
            ),
        )
        await self._db.commit()
        return token

    async def validate_token(self, token: str) -> Optional[TokenRecord]:
        """Validate a token. Returns TokenRecord if valid, None otherwise."""
        cursor = await self._db.execute(
            "SELECT * FROM api_tokens WHERE token = ?", (token,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        record = TokenRecord(row)
        if record.revoked:
            return None
        if record.expires_at is not None and time.time() > record.expires_at:
            return None
        return record

    async def list_tokens(self, channel_id: int) -> list[TokenRecord]:
        """List all non-revoked tokens for a channel."""
        cursor = await self._db.execute(
            """
            SELECT * FROM api_tokens
            WHERE channel_id = ? AND revoked = 0
            ORDER BY created_at DESC
            """,
            (channel_id,),
        )
        rows = await cursor.fetchall()
        return [TokenRecord(r) for r in rows]

    async def list_user_tokens(
        self, channel_id: int, discord_user_id: int
    ) -> list[TokenRecord]:
        """List all non-revoked tokens for a user in a channel."""
        cursor = await self._db.execute(
            """
            SELECT * FROM api_tokens
            WHERE channel_id = ? AND discord_user_id = ? AND revoked = 0
            ORDER BY created_at DESC
            """,
            (channel_id, discord_user_id),
        )
        rows = await cursor.fetchall()
        return [TokenRecord(r) for r in rows]

    async def revoke_token(self, token_id: int) -> bool:
        """Revoke a token by its ID. Returns True if updated."""
        cursor = await self._db.execute(
            """
            UPDATE api_tokens
            SET revoked = 1, revoked_at = ?
            WHERE id = ? AND revoked = 0
            """,
            (time.time(), token_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_token_by_id(self, token_id: int) -> Optional[TokenRecord]:
        cursor = await self._db.execute(
            "SELECT * FROM api_tokens WHERE id = ?", (token_id,)
        )
        row = await cursor.fetchone()
        return TokenRecord(row) if row else None
