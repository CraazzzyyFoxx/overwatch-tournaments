# Import all enums from shared library and re-export
from enum import StrEnum

from shared.core.enums import *


# App-specific enum
class RouteTag(StrEnum):
    """Tags used to classify API routes"""

    ENCOUNTER = "🎮 Encounter"
    MATCH = "🎮 Match"
    TEAMS = "🎮 Teams"
    TOURNAMENT = "🏆 Tournament"
    STANDINGS = "🏆 Standings"
    STATISTICS = "📊 Statistics"
    HERO = "🦸 Hero"
    USER = "👤 User"
    LOGS = "📜 Logs"
    ACHIEVEMENTS = "🏅 Achievements"
    MAP = "🗺️ Map"
    GAMEMODE = "🎮 Gamemode"
    UTILITY = "🔧 Utility"
    ANALYTICS = "📈 Analytics"
