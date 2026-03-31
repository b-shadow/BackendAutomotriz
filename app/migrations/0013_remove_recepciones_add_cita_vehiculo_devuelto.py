# Generated migration for CU21 - Remove reception/inspection, add vehicle return timestamp

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0012_alter_cita_estado'),
    ]

    operations = [
        # 1. Add vehiculo_devuelto_at to Cita
        migrations.AddField(
            model_name='cita',
            name='vehiculo_devuelto_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Cuándo se marcó el vehículo como recolectado/devuelto al cliente',
                verbose_name='vehículo devuelto en'
            ),
        ),
        
        # 2. Remove RecepcionInspeccionDetalle model (must be done before removing RecepcionInspeccion due to FK)
        migrations.DeleteModel(
            name='RecepcionInspeccionDetalle',
        ),
        
        # 3. Remove RecepcionInspeccion model
        migrations.DeleteModel(
            name='RecepcionInspeccion',
        ),
    ]
