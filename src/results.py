"""Results tracking and persistence."""

import aiosqlite
from datetime import datetime
from typing import Optional
import json


class ResultsDB:
    """SQLite database for tournament results."""

    def __init__(self, db_path: str = "results/battles.db"):
        self.db_path = db_path

    async def initialize(self):
        """Create tables if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS tournaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    format TEXT NOT NULL,
                    n_battles INTEGER NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    results_json TEXT
                );

                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    model_id TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS elo_ratings (
                    model_id INTEGER NOT NULL,
                    format TEXT NOT NULL,
                    elo INTEGER DEFAULT 1500,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    last_updated TIMESTAMP,
                    PRIMARY KEY (model_id, format),
                    FOREIGN KEY (model_id) REFERENCES models(id)
                );

                CREATE TABLE IF NOT EXISTS matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER,
                    format TEXT NOT NULL,
                    player1_model TEXT NOT NULL,
                    player2_model TEXT NOT NULL,
                    winner_model TEXT,
                    played_at TIMESTAMP NOT NULL,
                    replay_file TEXT,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
                );
            """)
            await db.commit()

    async def save_tournament(self, config, models, results):
        """Save tournament results."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO tournaments (name, format, n_battles, started_at, completed_at, results_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (config.name, config.format, config.n_battles,
                 datetime.now(), datetime.now(), json.dumps(results))
            )
            await db.commit()

    async def get_leaderboard(self, format: str = "gen4ou", limit: int = 20):
        """Get Elo leaderboard for a format."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT m.name, e.elo, e.wins, e.losses
                   FROM elo_ratings e
                   JOIN models m ON e.model_id = m.id
                   WHERE e.format = ?
                   ORDER BY e.elo DESC
                   LIMIT ?""",
                (format, limit)
            )
            return await cursor.fetchall()

    async def update_elo(self, winner: str, loser: str, format: str):
        """Update Elo ratings after a match."""
        K = 32  # K-factor

        async with aiosqlite.connect(self.db_path) as db:
            # Get current ratings
            cursor = await db.execute(
                """SELECT m.name, COALESCE(e.elo, 1500) as elo
                   FROM models m
                   LEFT JOIN elo_ratings e ON m.id = e.model_id AND e.format = ?
                   WHERE m.name IN (?, ?)""",
                (format, winner, loser)
            )
            ratings = {row[0]: row[1] for row in await cursor.fetchall()}

            winner_elo = ratings.get(winner, 1500)
            loser_elo = ratings.get(loser, 1500)

            # Calculate new ratings
            expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
            expected_loser = 1 - expected_winner

            new_winner_elo = round(winner_elo + K * (1 - expected_winner))
            new_loser_elo = round(loser_elo + K * (0 - expected_loser))

            # Update (upsert)
            await db.execute(
                """INSERT INTO elo_ratings (model_id, format, elo, wins, last_updated)
                   SELECT id, ?, ?, 1, ?
                   FROM models WHERE name = ?
                   ON CONFLICT(model_id, format) DO UPDATE SET
                   elo = ?, wins = wins + 1, last_updated = ?""",
                (format, new_winner_elo, datetime.now(), winner,
                 new_winner_elo, datetime.now())
            )
            await db.execute(
                """INSERT INTO elo_ratings (model_id, format, elo, losses, last_updated)
                   SELECT id, ?, ?, 1, ?
                   FROM models WHERE name = ?
                   ON CONFLICT(model_id, format) DO UPDATE SET
                   elo = ?, losses = losses + 1, last_updated = ?""",
                (format, new_loser_elo, datetime.now(), loser,
                 new_loser_elo, datetime.now())
            )
            await db.commit()
