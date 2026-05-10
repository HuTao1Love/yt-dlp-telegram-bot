import os
import sqlite3
from typing import List, Optional

import aiosqlite


class Storage:
    def __init__(self, path: str = "data/allowed_ids.db"):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS allowed_users(id INTEGER PRIMARY KEY)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles(
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT
            )
            """
        )
        cur.execute("CREATE TABLE IF NOT EXISTS allowed_groups(id INTEGER PRIMARY KEY)")
        con.commit()
        con.close()

    async def list_users(self) -> List[int]:
        async with aiosqlite.connect(self.path) as con:
            cur = await con.execute("SELECT id FROM allowed_users")
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    async def list_groups(self) -> List[int]:
        async with aiosqlite.connect(self.path) as con:
            cur = await con.execute("SELECT id FROM allowed_groups")
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    async def add_user(self, id: int) -> bool:
        async with aiosqlite.connect(self.path) as con:
            cur = await con.execute("INSERT OR IGNORE INTO allowed_users(id) VALUES(?)", (id,))
            await con.commit()
            return cur.rowcount > 0

    async def upsert_user_profile(
        self,
        id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
    ) -> None:
        async with aiosqlite.connect(self.path) as con:
            await con.execute(
                """
                INSERT INTO user_profiles(id, username, first_name, last_name)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name
                """,
                (id, username, first_name, last_name),
            )
            await con.commit()

    async def get_user_profile(self, id: int):
        async with aiosqlite.connect(self.path) as con:
            cur = await con.execute("SELECT username, first_name, last_name FROM user_profiles WHERE id = ?", (id,))
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "username": row[0],
                "first_name": row[1],
                "last_name": row[2],
            }

    async def remove_user(self, id: int) -> bool:
        async with aiosqlite.connect(self.path) as con:
            cur = await con.execute("DELETE FROM allowed_users WHERE id = ?", (id,))
            await con.commit()
            return cur.rowcount > 0

    async def add_group(self, id: int) -> bool:
        async with aiosqlite.connect(self.path) as con:
            cur = await con.execute("INSERT OR IGNORE INTO allowed_groups(id) VALUES(?)", (id,))
            await con.commit()
            return cur.rowcount > 0

    async def remove_group(self, id: int) -> bool:
        async with aiosqlite.connect(self.path) as con:
            cur = await con.execute("DELETE FROM allowed_groups WHERE id = ?", (id,))
            await con.commit()
            return cur.rowcount > 0
