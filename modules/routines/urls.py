from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    RoutineDashboardView,
    RoutineDeviationViewSet,
    RoutineExecutionViewSet,
    RoutineStepResponseViewSet,
    RoutineStepViewSet,
    RoutineTemplateViewSet,
)


router = DefaultRouter()
router.register("templates", RoutineTemplateViewSet, basename="routine-template")
router.register("steps", RoutineStepViewSet, basename="routine-step")
router.register("executions", RoutineExecutionViewSet, basename="routine-execution")
router.register("responses", RoutineStepResponseViewSet, basename="routine-step-response")
router.register("deviations", RoutineDeviationViewSet, basename="routine-deviation")

urlpatterns = [
    path("dashboard/", RoutineDashboardView.as_view(), name="routines-dashboard"),
    path("", include(router.urls)),
]
