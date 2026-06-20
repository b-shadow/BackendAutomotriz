from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("administracion_acceso_configuracion", "0002_alter_auditoria_options_alter_suscripcion_options_and_more"),
        ("comunicacion_control_inteligencia", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DispositivoPush",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token", models.CharField(db_index=True, max_length=255, unique=True, verbose_name="token FCM")),
                (
                    "plataforma",
                    models.CharField(
                        choices=[("WEB", "Web"), ("ANDROID", "Android"), ("IOS", "iOS")],
                        default="WEB",
                        max_length=20,
                        verbose_name="plataforma",
                    ),
                ),
                ("device_label", models.CharField(blank=True, max_length=120, null=True, verbose_name="nombre dispositivo")),
                ("user_agent", models.CharField(blank=True, max_length=500, null=True, verbose_name="user agent")),
                ("activo", models.BooleanField(db_index=True, default=True, verbose_name="activo")),
                ("ultimo_registro_at", models.DateTimeField(auto_now=True, verbose_name="ultimo registro")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="creado en")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="actualizado en")),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispositivos_push",
                        to="administracion_acceso_configuracion.empresa",
                        verbose_name="empresa",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispositivos_push",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dispositivo Push",
                "verbose_name_plural": "Dispositivos Push",
                "db_table": "dispositivos_push",
            },
        ),
        migrations.AddIndex(
            model_name="dispositivopush",
            index=models.Index(fields=["empresa", "usuario", "activo"], name="dispositivo_empresa_usuario_activo_idx"),
        ),
    ]
