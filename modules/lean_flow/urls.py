# modules/lean_flow/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    FlowBoardViewSet, FlowColumnViewSet, FlowCardViewSet,
    KanbanFlowConfigViewSet, KanbanCardViewSet,
    ConwipLineViewSet, ConwipLineStationViewSet, ConwipTicketViewSet,
    DDMRPBufferViewSet, DDMRPRecommendationViewSet,
)

router = DefaultRouter()
# Layer 1 - Visual Board
router.register(r"boards",  FlowBoardViewSet,  basename="flow-board")
router.register(r"columns", FlowColumnViewSet, basename="flow-column")
router.register(r"cards",   FlowCardViewSet,   basename="flow-card")
# Layer 2 - Kanban
router.register(r"kanban/flows", KanbanFlowConfigViewSet, basename="kanban-flow")
router.register(r"kanban/cards", KanbanCardViewSet,       basename="kanban-card")
# Layer 3 - CONWIP
router.register(r"conwip/lines",    ConwipLineViewSet,        basename="conwip-line")
router.register(r"conwip/stations", ConwipLineStationViewSet, basename="conwip-station")
router.register(r"conwip/tickets",  ConwipTicketViewSet,      basename="conwip-ticket")
# Layer 4 - DDMRP
router.register(r"ddmrp/buffers",         DDMRPBufferViewSet,         basename="ddmrp-buffer")
router.register(r"ddmrp/recommendations", DDMRPRecommendationViewSet, basename="ddmrp-reco")

urlpatterns = [
    path("", include(router.urls)),
]
