from shared.messaging.config import (
    CACHE_INVALIDATION_APP_QUEUE,
    CACHE_INVALIDATION_TOURNAMENT_QUEUE,
)


def test_cache_invalidation_consumers_use_distinct_queues() -> None:
    # One queue per consuming service, never a shared one: two consumers on the
    # same queue would round-robin the messages between them, so each service
    # would drop half of its own cache invalidations. Same reason the
    # tournament.changed contour this replaced had two queues.
    assert CACHE_INVALIDATION_APP_QUEUE.name == "cache_invalidation_app_service"
    assert CACHE_INVALIDATION_TOURNAMENT_QUEUE.name == "cache_invalidation_tournament_service"
    assert CACHE_INVALIDATION_APP_QUEUE.name != CACHE_INVALIDATION_TOURNAMENT_QUEUE.name
    # `#`, not `*`: the routing key is `cache.invalidated.<scope_kind>.<scope_id>`,
    # which is one segment deeper than a single-wildcard binding matches.
    assert CACHE_INVALIDATION_APP_QUEUE.routing_key == "cache.invalidated.#"
    assert CACHE_INVALIDATION_TOURNAMENT_QUEUE.routing_key == "cache.invalidated.#"
