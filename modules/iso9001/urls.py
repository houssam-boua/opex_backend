# modules/iso9001/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ISO9001ClauseViewSet, ComplianceAssessmentViewSet, NonConformityViewSet,
    CorrectiveActionViewSet, ISODocumentViewSet,
    ISO9001EvaluationSessionViewSet, ISO9001QuestionViewSet, ISO9001ResponseViewSet
)

router = DefaultRouter()
# Enterprise backbone
router.register(r"clauses", ISO9001ClauseViewSet, basename="iso-clause")
router.register(r"assessments", ComplianceAssessmentViewSet, basename="iso-assessment")
router.register(r"non-conformities", NonConformityViewSet, basename="iso-non-conformity")
router.register(r"corrective-actions", CorrectiveActionViewSet, basename="iso-corrective-action")
router.register(r"documents", ISODocumentViewSet, basename="iso-document")
# Legacy compatibility bridge
router.register(r"sessions", ISO9001EvaluationSessionViewSet, basename="iso-session")
router.register(r"questions", ISO9001QuestionViewSet, basename="iso-question")
router.register(r"responses", ISO9001ResponseViewSet, basename="iso-response")

urlpatterns = [
    path("", include(router.urls)),
]
