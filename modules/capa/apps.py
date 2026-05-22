from django.apps import AppConfig


class CapaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.capa"
    label = "capa"

    def ready(self):
        import modules.capa.signals  # noqa: F401

