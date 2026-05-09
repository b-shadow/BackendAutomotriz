import os
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from modulos.administracion_acceso_configuracion.models import Plan

def seed_plans():
    plans = [
        {
            "codigo": "STARTER",
            "nombre": "Plan Starter",
            "descripcion": "Ideal para pequeños talleres que están comenzando. Incluye gestión de vehículos, citas básicas y hasta 2 usuarios.",
            "duracion_dias": 30,
            "precio_centavos": 2900,
            "moneda": "USD",
            "activo": True
        },
        {
            "codigo": "PRO",
            "nombre": "Plan Pro",
            "descripcion": "Para talleres en crecimiento. Gestión avanzada de inventario, múltiples bahías de trabajo y hasta 10 usuarios.",
            "duracion_dias": 30,
            "precio_centavos": 7900,
            "moneda": "USD",
            "activo": True
        },
        {
            "codigo": "ENTERPRISE",
            "nombre": "Plan Enterprise",
            "descripcion": "Control total para grandes centros automotrices. Reportes personalizados, inteligencia artificial ilimitada y usuarios ilimitados.",
            "duracion_dias": 30,
            "precio_centavos": 19900,
            "moneda": "USD",
            "activo": True
        }
    ]

    for plan_data in plans:
        plan, created = Plan.objects.get_or_create(
            codigo=plan_data["codigo"],
            defaults=plan_data
        )
        if created:
            print(f"Plan creado: {plan.nombre}")
        else:
            # Actualizar si ya existe
            for key, value in plan_data.items():
                setattr(plan, key, value)
            plan.save()
            print(f"Plan actualizado: {plan.nombre}")

if __name__ == "__main__":
    seed_plans()
