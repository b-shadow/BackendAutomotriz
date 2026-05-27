import os
import sys
import django

# Add the backend directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.desarrollo')
django.setup()

from modulos.administracion_acceso_configuracion.models import Empresa

def seed_empresas():
    empresas = [
        {"nombre": "Taller Acme", "slug": "acme"},
        {"nombre": "Servicios Globex", "slug": "globex"},
    ]

    for data in empresas:
        empresa, created = Empresa.objects.get_or_create(
            slug=data["slug"],
            defaults=data
        )
        if created:
            print(f"Empresa creada: {empresa.nombre} ({empresa.slug})")
        else:
            print(f"Empresa ya existe: {empresa.nombre} ({empresa.slug})")

if __name__ == "__main__":
    seed_empresas()
