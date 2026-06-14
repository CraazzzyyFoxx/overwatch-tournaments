from src.core import db
from src.services.encounter import flows
from src.services.tournament import service as tournament_service


async def bulk_create() -> None:
    async with db.async_session_maker() as session:
        tournaments = await tournament_service.get_all(session, is_finished=False)
        for tournament in tournaments:
            await flows.bulk_create_for_tournament_from_challonge(session, tournament.id)
