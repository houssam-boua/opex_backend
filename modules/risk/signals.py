# modules/risk/signals.py
from django.dispatch import Signal

# Emitted when a risk score is updated and requires escalation (e.g. >= 16)
risk_escalated = Signal() # provides_args=["risk", "assessor"]
