"""SQLPilot Local Agent.

Runs locally on user's machine, keeping SQLite database files and raw records
100% on localhost while communicating with Vercel frontend.
"""

from sqlpilot.agent.service import LocalAgentService

__all__ = ["LocalAgentService"]
