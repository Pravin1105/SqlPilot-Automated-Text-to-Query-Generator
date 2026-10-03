import sys
from pathlib import Path

# Ensure repo root is always in sys.path
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from sqlpilot.agent.service import LocalAgentService

__all__ = ["LocalAgentService"]
