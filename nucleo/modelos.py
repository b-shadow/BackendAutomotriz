"""
Modelos base para toda la aplicación.
Incluye UUID, timestamps y métodos comunes.
"""
import uuid
from django.db import models
from django.utils.timezone import now


class BaseModel(models.Model):
    """
    Modelo base abstracto con campos comunes a toda la app.
    - id: UUID primario
    - creado_en: timestamp de creación
    - actualizado_en: timestamp de actualización
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.__class__.__name__} ({self.id})"
