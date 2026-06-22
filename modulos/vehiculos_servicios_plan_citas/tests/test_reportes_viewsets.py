from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from modulos.administracion_acceso_configuracion.models import Empresa, Rol, Usuario
from modulos.inventario_proveedores_administracion.models import (
    EstadoCompra,
    EstadoPagoTaller,
    EstadoSolicitudRepuesto,
    EstadoVentaMostrador,
    Compra,
    ItemInventario,
    PagoTaller,
    SolicitudRepuesto,
    TipoOrigenPagoTaller,
    VentaMostrador,
)
from modulos.vehiculos_servicios_plan_citas.models import (
    CanalOrigenCita,
    Cita,
    CitaDetalle,
    EstadoCita,
    EstadoPlanServicioDetalle,
    ServicioCatalogo,
    Vehiculo,
)
from modulos.vehiculos_servicios_plan_citas.viewsets.reportes_viewsets import ReportesViewSet


class ReportesViewSetTestCase(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.empresa = Empresa.objects.create(nombre="Taller QA", slug="taller-qa")
        self.rol = Rol.objects.create(empresa=self.empresa, nombre="ADMIN")
        self.rol_usuario = Rol.objects.create(empresa=self.empresa, nombre="USUARIO")
        self.rol_asesor = Rol.objects.create(empresa=self.empresa, nombre="ASESOR DE SERVICIO")
        self.rol_mecanico = Rol.objects.create(empresa=self.empresa, nombre="MECANICO")
        self.rol_administrativo = Rol.objects.create(empresa=self.empresa, nombre="ADMINISTRATIVO")
        self.rol_almacenero = Rol.objects.create(empresa=self.empresa, nombre="ALMACENERO")
        self.user = Usuario.objects.create(
            empresa=self.empresa,
            rol=self.rol,
            email="admin@qa.com",
            nombres="Admin",
            apellidos="QA",
            is_active=True,
        )
        self.user_cliente = Usuario.objects.create(
            empresa=self.empresa,
            rol=self.rol_usuario,
            email="cliente@qa.com",
            nombres="Cliente",
            apellidos="QA",
            is_active=True,
        )
        self.user_asesor = Usuario.objects.create(
            empresa=self.empresa,
            rol=self.rol_asesor,
            email="asesor@qa.com",
            nombres="Asesor",
            apellidos="QA",
            is_active=True,
        )
        self.user_mecanico = Usuario.objects.create(
            empresa=self.empresa,
            rol=self.rol_mecanico,
            email="mecanico@qa.com",
            nombres="Mecanico",
            apellidos="QA",
            is_active=True,
        )
        self.user_administrativo = Usuario.objects.create(
            empresa=self.empresa,
            rol=self.rol_administrativo,
            email="administrativo@qa.com",
            nombres="Administrativo",
            apellidos="QA",
            is_active=True,
        )
        self.user_almacenero = Usuario.objects.create(
            empresa=self.empresa,
            rol=self.rol_almacenero,
            email="almacen@qa.com",
            nombres="Almacen",
            apellidos="QA",
            is_active=True,
        )

        self.servicio = ServicioCatalogo.objects.create(
            empresa=self.empresa,
            codigo="SVC001",
            nombre="Cambio aceite",
            tiempo_estandar_min=60,
            precio_base=100,
            activo=True,
        )

        self.vehiculo_a = Vehiculo.objects.create(
            empresa=self.empresa,
            propietario=self.user,
            placa="ABC123",
            marca="Toyota",
            modelo="Corolla",
            anio=2020,
            kilometraje_actual=10000,
        )
        self.vehiculo_b = Vehiculo.objects.create(
            empresa=self.empresa,
            propietario=self.user,
            placa="XYZ999",
            marca="Nissan",
            modelo="Sentra",
            anio=2021,
            kilometraje_actual=20000,
        )

        now = timezone.now()

        self.cita_a1 = Cita.objects.create(
            empresa=self.empresa,
            vehiculo=self.vehiculo_a,
            cliente=self.user_cliente,
            estado=EstadoCita.FINALIZADA,
            canal_origen=CanalOrigenCita.ASESOR,
            fecha_hora_inicio_programada=now - timedelta(days=2, hours=3),
            fecha_hora_fin_programada=now - timedelta(days=2, hours=1),
            duracion_estimada_min=120,
            llegada_real_at=now - timedelta(days=2, hours=3),
            finalizada_at=now - timedelta(days=2, hours=1),
        )
        self.cita_a2 = Cita.objects.create(
            empresa=self.empresa,
            vehiculo=self.vehiculo_a,
            cliente=self.user_cliente,
            estado=EstadoCita.EN_PROCESO,
            canal_origen=CanalOrigenCita.CLIENTE,
            fecha_hora_inicio_programada=now - timedelta(hours=1),
            fecha_hora_fin_programada=now + timedelta(hours=1),
            duracion_estimada_min=120,
            llegada_real_at=now - timedelta(minutes=45),
            asesor_responsable=self.user_asesor,
        )
        self.cita_b1 = Cita.objects.create(
            empresa=self.empresa,
            vehiculo=self.vehiculo_b,
            cliente=self.user_cliente,
            estado=EstadoCita.CANCELADA,
            canal_origen=CanalOrigenCita.CLIENTE,
            fecha_hora_inicio_programada=now - timedelta(days=5, hours=1),
            fecha_hora_fin_programada=now - timedelta(days=5),
            duracion_estimada_min=60,
        )

        CitaDetalle.objects.create(
            empresa=self.empresa,
            cita=self.cita_a1,
            servicio_catalogo=self.servicio,
            estado=EstadoPlanServicioDetalle.FINALIZADO,
            tiempo_estandar_min=60,
            precio_referencial=100,
        )
        CitaDetalle.objects.create(
            empresa=self.empresa,
            cita=self.cita_a2,
            servicio_catalogo=self.servicio,
            estado=EstadoPlanServicioDetalle.PROGRAMADO,
            tiempo_estandar_min=30,
            precio_referencial=80,
        )

        PagoTaller.objects.create(
            empresa=self.empresa,
            tipo_origen=TipoOrigenPagoTaller.CITA,
            cita=self.cita_a1,
            estado=EstadoPagoTaller.RECIBIDO,
            monto_total=250,
            metodo_pago="EFECTIVO",
            moneda="BOB",
            recibido_at=now - timedelta(days=1),
        )
        VentaMostrador.objects.create(
            empresa=self.empresa,
            cliente_usuario=self.user_cliente,
            vendido_por=self.user_administrativo,
            estado=EstadoVentaMostrador.CONFIRMADA,
            subtotal=100,
            total=100,
        )
        Compra.objects.create(
            empresa=self.empresa,
            numero_documento="COMP-001",
            estado=EstadoCompra.CONFIRMADA,
            fecha_compra=now.date(),
            subtotal=200,
            total=200,
            registrado_por=self.user_administrativo,
        )
        ItemInventario.objects.create(
            empresa=self.empresa,
            codigo="ITM-LOW",
            nombre="Filtro de aceite",
            tipo_item="REPUESTO",
            unidad_medida="pieza",
            stock_actual=1,
            stock_minimo=3,
            costo_promedio=10,
            precio_venta=20,
            activo=True,
        )
        SolicitudRepuesto.objects.create(
            empresa=self.empresa,
            cita=self.cita_a2,
            solicitado_por=self.user_mecanico,
            aprobado_por_asesor=self.user_asesor,
            estado=EstadoSolicitudRepuesto.APROBADA_POR_ASESOR,
        )

    def _run_action(self, action_name, query_params="", user=None):
        view = ReportesViewSet.as_view({"get": action_name})
        request = self.factory.get(f"/api/reportes/{action_name}/{query_params}")
        force_authenticate(request, user=user or self.user)
        return view(request)

    def test_global_stats_includes_extended_kpis_and_ranking(self):
        resp = self._run_action("global_stats")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("kpis", resp.data)
        self.assertIn("vehiculos_en_taller", resp.data["kpis"])
        self.assertIn("vehiculos_total_sistema", resp.data["kpis"])
        self.assertIn("ratio_vehiculos_en_taller_pct", resp.data["kpis"])
        self.assertIn("ranking", resp.data)
        self.assertIn("vehiculo_mas_citas", resp.data["ranking"])

    def test_vehiculo_report_returns_detail_history_and_time_kpis(self):
        resp = self._run_action("vehiculo", "?placa=ABC123")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("vehiculo", resp.data)
        self.assertEqual(resp.data["vehiculo"]["placa"], "ABC123")
        self.assertIn("detalles_historial", resp.data)
        self.assertGreaterEqual(len(resp.data["detalles_historial"]), 1)
        self.assertIn("tiempo_total_taller_horas", resp.data["kpis"])
        self.assertIn("tasa_detalles_resueltos_pct", resp.data["kpis"])

    def test_vehiculo_report_without_plate_returns_top_rankings(self):
        resp = self._run_action("vehiculo")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("top_vehiculos", resp.data)
        self.assertIn("top_vehiculos_detalles_resueltos", resp.data)

    def test_dashboard_kpis_admin_returns_sections_summary_and_financial_inventory_kpis(self):
        resp = self._run_action("dashboard_kpis", user=self.user)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rol"], "ADMIN")
        self.assertIn("summary", resp.data)
        self.assertIn("sections", resp.data)
        self.assertIn("ingresos_mes", resp.data["kpis"])
        self.assertIn("items_stock_bajo", resp.data["kpis"])

    def test_dashboard_kpis_usuario_is_scoped_to_own_activity(self):
        resp = self._run_action("dashboard_kpis", user=self.user_cliente)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rol"], "USUARIO")
        self.assertIn("mis_vehiculos", resp.data["kpis"])
        self.assertIn("mis_citas_proximas", resp.data["kpis"])
        self.assertNotIn("ingresos_mes", resp.data["kpis"])

    def test_dashboard_kpis_almacenero_includes_inventory_metrics(self):
        resp = self._run_action("dashboard_kpis", user=self.user_almacenero)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rol"], "ALMACENERO")
        self.assertIn("items_stock_bajo", resp.data["kpis"])
        self.assertIn("solicitudes_pendientes_almacen", resp.data["kpis"])
