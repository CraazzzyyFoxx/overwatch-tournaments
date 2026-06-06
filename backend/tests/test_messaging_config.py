from shared.messaging.config import (
    TOURNAMENT_CHANGED_APP_QUEUE,
    TOURNAMENT_CHANGED_TOURNAMENT_QUEUE,
)


def test_tournament_changed_consumers_use_distinct_queues() -> None:
    assert TOURNAMENT_CHANGED_APP_QUEUE.name == "tournament_changed_app_service"
    assert TOURNAMENT_CHANGED_TOURNAMENT_QUEUE.name == "tournament_changed_tournament_service"
    assert TOURNAMENT_CHANGED_APP_QUEUE.name != TOURNAMENT_CHANGED_TOURNAMENT_QUEUE.name
    assert TOURNAMENT_CHANGED_APP_QUEUE.routing_key == "tournament.changed.*"
    assert TOURNAMENT_CHANGED_TOURNAMENT_QUEUE.routing_key == "tournament.changed.*"
