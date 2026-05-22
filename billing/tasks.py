# billing/tasks.py
from celery import shared_task
from django.utils import timezone
from core.models import Tenant


@shared_task(name="billing.tasks.check_expired_subscriptions")
def check_expired_subscriptions():
    """
    Runs daily at midnight (registered in celery.py Beat schedule).
    Finds tenants whose subscription_ends_at has passed and sets status = "expired".
    Also finds trial tenants whose trial_ends_at has passed and sets status = "expired".
    """
    today = timezone.localdate()

    # Expire paid subscriptions that have passed their end date
    expired_paid = Tenant.objects.filter(
        status="active",
        subscription_ends_at__lt=today,
    )
    count_paid = expired_paid.update(status="expired")

    # Expire trials that have passed their trial end date
    expired_trial = Tenant.objects.filter(
        status="trial",
        trial_ends_at__lt=today,
    )
    count_trial = expired_trial.update(status="expired")

    total = count_paid + count_trial
    return f"Expired {total} tenants ({count_paid} paid, {count_trial} trial)"
