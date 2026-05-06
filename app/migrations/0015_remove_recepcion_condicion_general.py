# Generated migration to remove condicion_general field from RecepcionVehiculo

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0014_add_recepcion_vehiculo'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='recepcionvehiculo',
            name='condicion_general',
        ),
    ]
