"""
Celery configuration for OPEX project.

Placed inside opex_main/ (standard Django-Celery pattern) so that
`celery -A opex_main worker` discovers it correctly without
shadowing the `celery` package.
"""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opex_main.settings")

app = Celery("opex")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()   # Discovers tasks.py in all INSTALLED_APPS


# Scheduled tasks (Celery Beat)
app.conf.beat_schedule = {

    # Rappels CAPA arrivant à échéance — tous les jours à 8h00
    "capa-due-reminders-daily": {
        "task":     "modules.capa.tasks.send_due_reminders",
        "schedule": crontab(hour=8, minute=0),
    },

    # Rapport hebdomadaire Gemba — chaque lundi à 7h00
    "gemba-weekly-report": {
        "task":     "modules.gemba.tasks.send_weekly_summary",
        "schedule": crontab(hour=7, minute=0, day_of_week=1),
    },

    # Vérification abonnements expirés — tous les jours à minuit
    "check-expired-subscriptions": {
        "task":     "billing.tasks.check_expired_subscriptions",
        "schedule": crontab(hour=0, minute=0),
    },

    # Vérification des certifications expirant dans < 30 jours — tous les jours à 6h00
    "check-expiring-certifications": {
        "task":     "modules.skills.tasks.check_expiring_certifications_task",
        "schedule": crontab(hour=6, minute=0),
    },

    # Vérification d'expiration des documents ISO9001 — tous les jours à 7h00
    "check-iso-document-expiry": {
        "task":     "modules.iso9001.tasks.check_iso_document_expiry_task",
        "schedule": crontab(hour=7, minute=0),
    },

    # Détection des routines obligatoires manquées — tous les jours à 5h30
    "routines-check-missed-executions-daily": {
        "task":     "modules.routines.tasks.check_missed_routine_executions_task",
        "schedule": crontab(hour=5, minute=30),
    },

    # Détection des vérifications Poka-Yoke en retard — tous les jours à 6h00
    "poka-yoke-check-overdue-verifications-daily": {
        "task":     "modules.poka_yoke.tasks.check_overdue_poka_yoke_verifications_task",
        "schedule": crontab(hour=6, minute=0),
    },
}
