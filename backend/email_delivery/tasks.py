from celery import shared_task

from .services.campaigns import execute_campaign_send_job


@shared_task(
    bind=True,
    name="email_delivery.deliver_campaign_send_job",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def deliver_campaign_send_job(task, job_id):
    try:
        return execute_campaign_send_job(job_id)
    except Exception:
        if task.request.retries >= task.max_retries:
            from .services.campaigns import fail_campaign_send_job

            fail_campaign_send_job(
                job_id,
                "The delivery worker failed after its automatic retries.",
            )
        raise
