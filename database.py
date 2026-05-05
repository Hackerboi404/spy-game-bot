import sqlite3
import asyncio
from typing import Dict, Optional

# Rank Thresholds
RANKS = {
    0: "Rookie",
    100: "Agent",
    300: "Detective",
    600: "Special Agent",
    1000: "Master Spy",
    2000: "Legend"
}

class Database:
    def __init__(self, db_file="spygame.db"):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                xp INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def get_user(self, user_id: int, username: str = None) -> Dict:
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        if not row:
            # Create new user
            self.cursor.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)", 
                (user_id, username or "Unknown")
            )
            self.conn.commit()
            return {"user_id": user_id, "username": username, "xp": 0, "wins": 0, "losses": 0, "games_played": 0}
        
        # Update username if it changed
        if username and row[1] != username:
            self.cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            self.conn.commit()
            row = list(row)
            row[1] = username

        return {
            "user_id": row[0], "username": row[1], "xp": row[2],
            "wins": row[3], "losses": row[4], "games_played": row[5]
        }

    def update_xp(self, user_id: int, xp_change: int):
        self.cursor.execute(
            "UPDATE users SET xp = xp + ? WHERE user_id = ?", 
            (xp_change, user_id)
        )
        self.conn.commit()

    def increment_stat(self, user_id: int, stat: str):
        valid_stats = ['wins', 'losses', 'games_played']
        if stat in valid_stats:
            self.cursor.execute(
                f"UPDATE users SET {stat} = {stat} + 1 WHERE user_id = ?", 
                (user_id,)
            )
            self.conn.commit()

    def get_rank(self, xp: int) -> str:
        rank = "Rookie"
        for threshold, title in sorted(RANKS.items()):
            if xp >= threshold:
                rank = title
        return rank

    def get_leaderboard(self, limit=10):
        self.cursor.execute("SELECT username, xp FROM users ORDER BY xp DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

# Global DB Instance
db = Database()
