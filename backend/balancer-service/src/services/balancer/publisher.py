from shared.messaging.config import BALANCER_JOBS_QUEUE
from shared.observability import publish_message
from shared.schemas.events import BalancerJobEvent


class BalancerJobPublisher:
    def __init__(self, broker, logger) -> None:
        self._broker = broker
        self._logger = logger

    async def publish_job_requested(self, job_id: str) -> None:
        event = BalancerJobEvent(job_id=job_id)
        await publish_message(
            self._broker,
            event.model_dump(),
            BALANCER_JOBS_QUEUE,
            logger=self._logger,
        )
