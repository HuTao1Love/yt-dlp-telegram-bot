import os
import sqlite3
from typing import List


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

    def list_users(self) -> List[int]:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute("SELECT id FROM allowed_users")
        rows = [r[0] for r in cur.fetchall()]
        con.close()
        return rows

    def list_groups(self) -> List[int]:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute("SELECT id FROM allowed_groups")
        rows = [r[0] for r in cur.fetchall()]
        con.close()
        return rows

    def add_user(self, id: int) -> bool:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        try:
            cur.execute("INSERT OR IGNORE INTO allowed_users(id) VALUES(?)", (id,))
            con.commit()
            changed = cur.rowcount > 0
        finally:
            con.close()
        return changed

    def upsert_user_profile(
        self,
        id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> None:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute(
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
        con.commit()
        con.close()

    def get_user_profile(self, id: int):
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute("SELECT username, first_name, last_name FROM user_profiles WHERE id = ?", (id,))
        row = cur.fetchone()
        con.close()
        if not row:
            return None
        return {
            "username": row[0],
            "first_name": row[1],
            "last_name": row[2],
        }

    def remove_user(self, id: int) -> bool:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute("DELETE FROM allowed_users WHERE id = ?", (id,))
        con.commit()
        changed = cur.rowcount > 0
        con.close()
        return changed

    def add_group(self, id: int) -> bool:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        try:
            cur.execute("INSERT OR IGNORE INTO allowed_groups(id) VALUES(?)", (id,))
            con.commit()
            changed = cur.rowcount > 0
        finally:
            con.close()
        return changed

    def remove_group(self, id: int) -> bool:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute("DELETE FROM allowed_groups WHERE id = ?", (id,))
        con.commit()
        changed = cur.rowcount > 0
        con.close()
        return changed
