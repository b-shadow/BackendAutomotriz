"""
Migration: Agregar campo session_revoked_at para logout simple.

Campo para invalidar todos los tokens de un usuario sin necesidad de
tabla de blacklist. Valida que token.iat >= user.session_revoked_at
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0006_add_notification_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="session_revoked_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Si está seteado, todos los tokens emitidos antes de esta fecha son inválidos",
                null=True,
                verbose_name="sesión revocada en",
            ),
        ),
    ]
