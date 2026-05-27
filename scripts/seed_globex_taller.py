import os
import sys
import django
from django.utils import timezone
from datetime import timedelta
import random

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.desarrollo')
django.setup()

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.vehiculos_servicios_plan_citas.models import Vehiculo, ServicioCatalogo, Cita, CitaDetalle, EstadoCita, EstadoPlanServicioDetalle
from modulos.inventario_proveedores_administracion.models import Factura, PagoTaller

def seed_taller():
    empresa = Empresa.objects.filter(slug="globex").first()
    if not empresa:
        print("La empresa 'globex' no existe. Ejecuta seed_empresas.py primero.")
        return
        
    print("Limpiando datos de prueba anteriores...")
    Factura.objects.filter(empresa=empresa, numero__startswith="F-GLOBEX").delete()
    PagoTaller.objects.filter(empresa=empresa, cita__vehiculo__empresa=empresa).delete()
    CitaDetalle.objects.filter(empresa=empresa).delete()
    Cita.objects.filter(empresa=empresa).delete()
    ServicioCatalogo.objects.filter(empresa=empresa).delete()
    Vehiculo.objects.filter(empresa=empresa).delete()
    
    # Usuarios (Clientes)
    clientes = []
    for i in range(3):
        cliente, _ = Usuario.objects.get_or_create(
            email=f"cliente{i}@globex.com",
            empresa=empresa,
            defaults={"nombres": f"Cliente {i}", "apellidos": "Globex", "telefono": f"12345678{i}", "is_active": True}
        )
        clientes.append(cliente)
    
    # Vehículos
    vehiculos = []
    marcas = ["Toyota", "Nissan", "Ford"]
    for i in range(3):
        vehiculo = Vehiculo.objects.create(
            empresa=empresa,
            propietario=clientes[i],
            placa=f"GLO-10{i}",
            marca=marcas[i],
            modelo="ModeloX",
            anio=2020 + i,
            color="Gris",
            kilometraje_actual=10000 * (i+1)
        )
        vehiculos.append(vehiculo)
    
    # Servicios del Catálogo con precios diferentes
    servicios_data = [
        ("MANT_GEN", "Mantenimiento General", 120, 150.00),
        ("ACEITE", "Cambio de Aceite", 30, 45.00),
        ("FRENOS", "Cambio de Pastillas de Freno", 60, 80.00),
        ("ALINEACION", "Alineación y Balanceo", 45, 60.00),
        ("MOTOR", "Ajuste de Motor", 240, 350.00)
    ]
    
    servicios = []
    for codigo, nombre, tiempo, precio in servicios_data:
        srv = ServicioCatalogo.objects.create(
            empresa=empresa,
            codigo=codigo,
            nombre=nombre,
            tiempo_estandar_min=tiempo,
            precio_base=precio
        )
        servicios.append(srv)
    
    # Citas pasadas y facturas
    for i in range(30):
        fecha_inicio = timezone.now() - timedelta(days=random.randint(1, 60))
        fecha_fin = fecha_inicio + timedelta(hours=random.randint(1, 4))
        v = random.choice(vehiculos)
        
        cita = Cita.objects.create(
            empresa=empresa,
            vehiculo=v,
            cliente=v.propietario,
            estado=EstadoCita.FINALIZADA,
            canal_origen="CLIENTE",
            fecha_hora_inicio_programada=fecha_inicio,
            fecha_hora_fin_programada=fecha_fin,
            duracion_estimada_min=120,
            motivo_visita=f"Visita de mantenimiento {i+1}"
        )
        
        # Elegir de 1 a 3 servicios al azar para esta cita
        servicios_cita = random.sample(servicios, random.randint(1, 3))
        total_cita = 0
        
        for srv in servicios_cita:
            CitaDetalle.objects.create(
                empresa=empresa,
                cita=cita,
                servicio_catalogo=srv,
                estado=EstadoPlanServicioDetalle.FINALIZADO,
                tiempo_estandar_min=srv.tiempo_estandar_min,
                precio_referencial=srv.precio_base
            )
            total_cita += float(srv.precio_base)
        
        # Pago
        pago = PagoTaller.objects.create(
            empresa=empresa,
            tipo_origen="CITA",
            cita=cita,
            estado="COMPLETADO",
            monto_total=total_cita,
            monto_real=total_cita,
            monto_cobrado=total_cita,
            monto_pagado=total_cita,
            metodo_pago=random.choice(["EFECTIVO", "TARJETA", "TRANSFERENCIA"])
        )
        
        # Factura
        Factura.objects.create(
            empresa=empresa,
            pago_taller=pago,
            numero=f"F-GLOBEX-{i+2000}",
            nit_razon_social=v.propietario.nombres,
            total=pago.monto_total
        )
        
    print(f"Se crearon exitosamente 30 citas, con servicios múltiples y facturas de prueba para la empresa {empresa.nombre}.")

if __name__ == "__main__":
    seed_taller()
