# Import all ORM models from the shared library.
# Mirrors parser-service/src/models/__init__.py so that v1 analytics code that
# does ``from src import models; models.Tournament`` keeps working unchanged.
from shared.models.achievements.achievement import *
from shared.models.analytics.analytics import *
from shared.models.balancer.balance import *
from shared.models.catalog.gamemode import *
from shared.models.catalog.hero import *
from shared.models.catalog.map import *
from shared.models.division_grid.division_grid import *
from shared.models.identity.auth_user import *
from shared.models.identity.social import *
from shared.models.identity.user import *
from shared.models.identity.user_merge_audit import *
from shared.models.ingestion.discord_channel import *
from shared.models.ingestion.log_processing import *
from shared.models.matches.match import *
from shared.models.registration.registration import *
from shared.models.tenancy.workspace import *
from shared.models.tournament.challonge import *
from shared.models.tournament.encounter import *
from shared.models.tournament.encounter_link import *
from shared.models.tournament.encounter_map import *
from shared.models.tournament.stage import *
from shared.models.tournament.standings import *
from shared.models.tournament.team import *
from shared.models.tournament.tournament import *
