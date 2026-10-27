"""Admin service layer for stage CRUD and bracket generation.

One concern per module, all on one ``StageServiceBase``; ``AdminStageService``
puts them back together and ``stage_service`` is the instance callers use.
"""

# Re-exported: ``standings.swiss_auto_round`` reads the item seeds through this module.
from src.domain.stage.seeds import collect_item_team_ids as _collect_item_team_ids
from src.services.admin.stage.best_of import StageBestOfMixin
from src.services.admin.stage.bracket import StageBracketMixin
from src.services.admin.stage.crud import StageCrudMixin, rule_values
from src.services.admin.stage.generation import StageGenerationMixin
from src.services.admin.stage.inputs import StageInputsMixin
from src.services.admin.stage.lifecycle import StageLifecycleMixin
from src.services.admin.stage.merge import StageMergeMixin
from src.services.admin.stage.qualification import StageQualificationMixin
from src.services.admin.stage.seeding import StageSeedingMixin


class AdminStageService(
    StageCrudMixin,
    StageInputsMixin,
    StageMergeMixin,
    StageBracketMixin,
    StageLifecycleMixin,
    StageSeedingMixin,
    StageGenerationMixin,
    StageBestOfMixin,
    StageQualificationMixin,
):
    """Every stage admin operation; each mixin's module holds one concern."""


stage_service = AdminStageService()
