"""
Script to generate all 18 OPEX module placeholder apps.
Run this once to create the directory structure.
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

MODULES = [
    ("gemba", "Gemba"),
    ("audits", "Audits"),
    ("iso9001", "Iso9001"),
    ("five_s", "FiveS"),
    ("tpm", "Tpm"),
    ("lean_flow", "LeanFlow"),
    ("vsm", "Vsm"),
    ("smed", "Smed"),
    ("sfm", "Sfm"),
    ("rotation_table", "RotationTable"),
    ("capa", "Capa"),
    ("risk", "Risk"),
    ("problem_solving", "ProblemSolving"),
    ("poka_yoke", "PokaYoke"),
    ("skills", "Skills"),
    ("visual_management", "VisualManagement"),
    ("routines", "Routines"),
    ("messaging", "Messaging"),
]

# Create modules/__init__.py
modules_dir = os.path.join(BASE, "modules")
os.makedirs(modules_dir, exist_ok=True)
with open(os.path.join(modules_dir, "__init__.py"), "w") as f:
    f.write("# modules package\n")

for name, class_name in MODULES:
    mod_dir = os.path.join(modules_dir, name)
    os.makedirs(mod_dir, exist_ok=True)

    # __init__.py
    with open(os.path.join(mod_dir, "__init__.py"), "w") as f:
        f.write(f"# modules.{name}\n")

    # apps.py
    with open(os.path.join(mod_dir, "apps.py"), "w") as f:
        f.write(f'''from django.apps import AppConfig


class {class_name}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.{name}"
    label = "{name}"
''')

    # models.py
    with open(os.path.join(mod_dir, "models.py"), "w") as f:
        f.write(f"# modules/{name}/models.py\n")

    # serializers.py
    with open(os.path.join(mod_dir, "serializers.py"), "w") as f:
        f.write(f"# modules/{name}/serializers.py\n")

    # views.py
    with open(os.path.join(mod_dir, "views.py"), "w") as f:
        f.write(f"# modules/{name}/views.py\n")

    # urls.py
    with open(os.path.join(mod_dir, "urls.py"), "w") as f:
        f.write("urlpatterns = []\n")

    # services.py
    with open(os.path.join(mod_dir, "services.py"), "w") as f:
        f.write(f"# modules/{name}/services.py\n")

    print(f"  Created modules/{name}/ (7 files)")

print(f"\nDone! Created {len(MODULES)} module placeholders.")
