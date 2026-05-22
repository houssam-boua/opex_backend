# modules/skills/models.py
"""
Skills Module — OPEX SaaS
Workforce Intelligence Layer and Polyvalence Matrix
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from shared.base import BaseModel
from accounts.managers import TenantManager


class SkillCategory(BaseModel):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "skills_categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Skill(BaseModel):
    category = models.ForeignKey(SkillCategory, on_delete=models.SET_NULL, null=True, related_name="skills")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "skills_skills"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.category.name if self.category else 'No Category'})"


class EmployeeSkill(BaseModel):
    """The Matrix Engine Core representing the ILUO scale."""
    employee = models.ForeignKey("accounts.Employee", on_delete=models.CASCADE, related_name="skills")
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="employee_skills")
    level = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        help_text="1: I (Beginner), 2: L (Intermediate), 3: U (Autonomous), 4: O (Trainer)"
    )
    target_level = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        help_text="Target ILUO level for the employee"
    )

    objects = TenantManager()

    class Meta:
        db_table = "skills_employee_skills"
        unique_together = ("employee", "skill")

    def __str__(self):
        return f"{self.employee.full_name} - {self.skill.name} (Level {self.level})"

    def sync_to_shared_action(self):
        """Generates training workload task if target_level > current level."""
        from shared.models import Action
        
        if self.target_level > self.level:
            action, _ = Action.objects.update_or_create(
                reference_id=self.id,
                module_source="skills",
                tenant=self.tenant,
                defaults={
                    "title": f"[Training Upgrade] {self.employee.full_name} for {self.skill.name}",
                    "description": f"Target level: {self.target_level}, Current level: {self.level}",
                    "priority": "medium",
                    "status": "open",
                    "assigned_to": None, # Unassigned, waiting for a trainer/manager to pick it up
                    "created_by": self.created_by,
                    "action_type": "training_upgrade",
                }
            )
            return action
        else:
            # If they reached the target level, close any existing open task
            Action.objects.filter(reference_id=self.id, module_source="skills", status__in=["open", "in_progress"]).update(status="done")
        return None


class TrainingSession(BaseModel):
    title = models.CharField(max_length=200)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="training_sessions")
    trainer = models.ForeignKey("accounts.Employee", on_delete=models.SET_NULL, null=True, related_name="trainings_led")
    date = models.DateField()
    attendees = models.ManyToManyField("accounts.Employee", related_name="trainings_attended", db_table="skills_training_attendees")

    objects = TenantManager()

    class Meta:
        db_table = "skills_training_sessions"
        ordering = ["-date"]

    def __str__(self):
        return f"Training: {self.title} on {self.date}"


class Certification(BaseModel):
    employee = models.ForeignKey("accounts.Employee", on_delete=models.CASCADE, related_name="certifications")
    name = models.CharField(max_length=200)
    issued_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "skills_certifications"
        ordering = ["expiry_date"]

    def __str__(self):
        return f"Cert: {self.name} for {self.employee.full_name}"
