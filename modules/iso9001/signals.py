# modules/iso9001/signals.py
from django.dispatch import Signal

# Emitted when a major or critical NonConformity is created
iso_nc_created = Signal() # provides_args=["non_conformity"]
