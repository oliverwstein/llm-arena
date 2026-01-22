"""Load and manage the team pool from Raw-Teams/ directory."""

import random
from pathlib import Path
from poke_env.teambuilder import Teambuilder


class TeamPool(Teambuilder):
    """
    Loads teams from markdown files in Showdown paste format.

    Each battle, a random team is selected from the pool.
    Both players draw from the same pool (may get the same team).
    The first Pokemon in each team file is the lead.
    """

    def __init__(self, teams_dir: str = "Raw-Teams"):
        """
        Load all teams from the specified directory.

        Args:
            teams_dir: Path to directory containing .md files with teams
        """
        super().__init__()  # Initialize base Teambuilder
        self.teams_dir = Path(teams_dir)
        self.teams: list[str] = []  # Packed team strings
        self.team_names: list[str] = []  # For logging
        self._load_teams()

    def _load_teams(self) -> None:
        """Load all .md files from the teams directory."""
        if not self.teams_dir.exists():
            raise FileNotFoundError(f"Teams directory not found: {self.teams_dir}")

        team_files = list(self.teams_dir.glob("*.md"))
        if not team_files:
            raise ValueError(f"No .md team files found in {self.teams_dir}")

        for team_file in team_files:
            paste = team_file.read_text()
            # poke-env's Teambuilder can parse Showdown paste format
            packed = self.join_team(self.parse_showdown_team(paste))
            self.teams.append(packed)
            self.team_names.append(team_file.stem)

        print(f"Loaded {len(self.teams)} teams: {', '.join(self.team_names)}")

    def yield_team(self) -> str:
        """Return a random team from the pool (called by poke-env)."""
        idx = random.randint(0, len(self.teams) - 1)
        return self.teams[idx]

    def get_team_count(self) -> int:
        """Return number of teams in the pool."""
        return len(self.teams)


# Singleton instance for convenience
_default_pool: TeamPool | None = None


def get_team_pool(teams_dir: str = "Raw-Teams") -> TeamPool:
    """Get or create the default team pool."""
    global _default_pool
    if _default_pool is None:
        _default_pool = TeamPool(teams_dir)
    return _default_pool
