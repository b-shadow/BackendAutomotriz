# Generated migration to remove plan versioning and enforce mandatory relationships

from django.db import migrations, models
import django.db.models.deletion


def validate_no_null_propietarios(apps, schema_editor):
    """
    Validación preventiva: Detecta vehículos sin propietario.
    Si existen, falla explícitamente con mensaje claro.
    """
    Vehiculo = apps.get_model('app', 'Vehiculo')
    count_null = Vehiculo.objects.filter(propietario__isnull=True).count()
    
    if count_null > 0:
        raise migrations.RunPython.Noop(
            f"ERROR: Se encontraron {count_null} vehículos sin propietario. "
            "No se puede completar la migración. "
            "Acción requerida: Asignar propietario a todos los vehículos antes de migrar. "
            "Si son vehículos huérfanos, eliminarlos primero. "
            "SQL: SELECT * FROM vehiculos WHERE propietario_id IS NULL;"
        )


def validate_no_null_servicios_catalogo(apps, schema_editor):
    """
    Validación preventiva: Detecta detalles de plan sin servicio de catálogo.
    Si existen, falla explícitamente con mensaje claro.
    """
    PlanServicioDetalle = apps.get_model('app', 'PlanServicioDetalle')
    count_null = PlanServicioDetalle.objects.filter(servicio_catalogo__isnull=True).count()
    
    if count_null > 0:
        raise migrations.RunPython.Noop(
            f"ERROR: Se encontraron {count_null} detalles de plan sin servicio de catálogo. "
            "No se puede completar la migración. "
            "Acción requerida: Asignar servicio_catalogo a todos los detalles antes de migrar. "
            "Si son detalles huérfanos, eliminarlos primero. "
            "SQL: SELECT * FROM planes_servicio_detalle WHERE servicio_catalogo_id IS NULL;"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0009_remove_planserviciovehiculo_planes_serv_vehicul_c49af7_idx_and_more"),
    ]

    operations = [
        # 0. Validaciones previas
        migrations.RunPython(
            validate_no_null_propietarios,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            validate_no_null_servicios_catalogo,
            reverse_code=migrations.RunPython.noop,
        ),
        
        # 1. Remove versioning fields from PlanServicioVehiculo
        migrations.RemoveField(
            model_name='planserviciovehiculo',
            name='version',
        ),
        migrations.RemoveField(
            model_name='planserviciovehiculo',
            name='es_actual',
        ),
        migrations.RemoveField(
            model_name='planserviciovehiculo',
            name='plan_anterior',
        ),
        
        # 2. Make Vehiculo.propietario NOT NULL (mandatory relationship)
        #    Change on_delete from SET_NULL to RESTRICT to prevent orphaned vehicles
        migrations.AlterField(
            model_name='vehiculo',
            name='propietario',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name='vehiculos',
                to='app.usuario',
                verbose_name='propietario',
                help_text='Usuario propietario del vehículo'
            ),
        ),
        
        # 3. Make PlanServicioDetalle.servicio_catalogo NOT NULL (mandatory relationship)
        #    Change on_delete from SET_NULL to RESTRICT to ensure details always have service reference
        migrations.AlterField(
            model_name='planserviciodetalle',
            name='servicio_catalogo',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name='planes_detalles',
                to='app.serviciocatalogo',
                verbose_name='servicio catálogo'
            ),
        ),
    ]
