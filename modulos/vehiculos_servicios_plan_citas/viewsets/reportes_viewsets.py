import logging
from datetime import datetime, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, TruncMonth
from rest_framework import response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from modulos.atencion_tecnica_ejecucion.models import EstadoPresupuestoCita, PresupuestoCita
from modulos.inventario_proveedores_administracion.models import EstadoPagoTaller, PagoTaller
from modulos.vehiculos_servicios_plan_citas.models import Cita, CitaDetalle, EstadoCita, ServicioCatalogo, Vehiculo

logger = logging.getLogger(__name__)


class ReportesViewSet(viewsets.ViewSet):
    """ViewSet para reportes de tablero."""

    permission_classes = [IsAuthenticated]

    def _get_fecha_range(self, request):
        desde_str = request.query_params.get("desde")
        hasta_str = request.query_params.get("hasta")

        hasta = datetime.now()
        desde = hasta - timedelta(days=30)

        if desde_str:
            try:
                desde = datetime.strptime(desde_str, "%Y-%m-%d")
            except ValueError:
                pass
        if hasta_str:
            try:
                hasta = datetime.strptime(hasta_str, "%Y-%m-%d")
            except ValueError:
                pass

        hasta = hasta.replace(hour=23, minute=59, second=59)
        return desde, hasta

    def _clean(self, value):
        return (value or "").strip()

    def _apply_cita_filters(self, queryset, request):
        placa = self._clean(request.query_params.get("placa"))
        vehiculo_id = self._clean(request.query_params.get("vehiculo_id"))
        marca = self._clean(request.query_params.get("marca"))
        modelo = self._clean(request.query_params.get("modelo"))
        estado_cita = self._clean(request.query_params.get("estado_cita"))
        canal = self._clean(request.query_params.get("canal_origen"))

        if placa:
            queryset = queryset.filter(vehiculo__placa__icontains=placa)
        if vehiculo_id:
            queryset = queryset.filter(vehiculo_id=vehiculo_id)
        if marca:
            queryset = queryset.filter(vehiculo__marca__icontains=marca)
        if modelo:
            queryset = queryset.filter(vehiculo__modelo__icontains=modelo)
        if estado_cita:
            queryset = queryset.filter(estado=estado_cita)
        if canal:
            queryset = queryset.filter(canal_origen=canal)

        return queryset

    @action(detail=False, methods=["get"])
    def global_stats(self, request, **kwargs):
        empresa = request.user.empresa
        desde, hasta = self._get_fecha_range(request)

        citas = Cita.objects.filter(empresa=empresa, created_at__gte=desde, created_at__lte=hasta)
        citas = self._apply_cita_filters(citas, request)

        total_citas = citas.count()
        citas_completadas = citas.filter(estado=EstadoCita.FINALIZADA).count()
        citas_canceladas = citas.filter(estado=EstadoCita.CANCELADA).count()
        citas_no_show = citas.filter(estado=EstadoCita.NO_SHOW).count()

        pagos = PagoTaller.objects.filter(empresa=empresa, cita__in=citas).exclude(estado=EstadoPagoTaller.ANULADO)
        ingresos_totales = float(pagos.aggregate(total=Sum("monto_total")).get("total") or 0)
        ticket_promedio = round(ingresos_totales / total_citas, 2) if total_citas > 0 else 0

        citas_por_fecha = (
            citas.annotate(fecha=TruncDate("created_at"))
            .values("fecha")
            .annotate(total=Count("id"))
            .order_by("fecha")
        )

        grafico_ingresos = []
        for c in citas_por_fecha:
            ingreso_fecha = (
                PagoTaller.objects.filter(empresa=empresa, cita__created_at__date=c["fecha"])
                .exclude(estado=EstadoPagoTaller.ANULADO)
                .aggregate(total=Sum("monto_total"))
                .get("total")
                or 0
            )
            grafico_ingresos.append(
                {
                    "fecha": c["fecha"].strftime("%Y-%m-%d") if c["fecha"] else "N/A",
                    "ingresos": float(ingreso_fecha),
                    "citas": c["total"],
                }
            )

        distribucion_estados = [
            {"name": e["estado"], "value": e["total"]}
            for e in citas.values("estado").annotate(total=Count("id")).order_by("-total")
        ]

        return response.Response(
            {
                "kpis": {
                    "ingresos_totales": ingresos_totales,
                    "citas_totales": total_citas,
                    "citas_completadas": citas_completadas,
                    "citas_canceladas": citas_canceladas,
                    "citas_no_show": citas_no_show,
                    "ticket_promedio": ticket_promedio,
                },
                "grafico_ingresos": grafico_ingresos,
                "distribucion_estados": distribucion_estados,
            }
        )

    @action(detail=False, methods=["get"])
    def vehiculo(self, request, **kwargs):
        empresa = request.user.empresa
        placa = self._clean(request.query_params.get("placa"))
        desde, hasta = self._get_fecha_range(request)

        if not placa:
            top_queryset = Cita.objects.filter(empresa=empresa, created_at__gte=desde, created_at__lte=hasta)
            top_queryset = self._apply_cita_filters(top_queryset, request)
            top_vehiculos = (
                top_queryset.values("vehiculo__placa", "vehiculo__marca", "vehiculo__modelo")
                .annotate(total_citas=Count("id"))
                .order_by("-total_citas")[:10]
            )
            datos = [
                {
                    "placa": v["vehiculo__placa"],
                    "vehiculo": f"{v['vehiculo__marca']} {v['vehiculo__modelo']}",
                    "visitas": v["total_citas"],
                }
                for v in top_vehiculos
                if v["vehiculo__placa"]
            ]
            return response.Response({"top_vehiculos": datos})

        vehiculo = Vehiculo.objects.filter(empresa=empresa, placa__iexact=placa).first()
        if not vehiculo:
            return response.Response({"error": "Vehiculo no encontrado"}, status=404)

        citas = Cita.objects.filter(
            vehiculo=vehiculo,
            empresa=empresa,
            created_at__gte=desde,
            created_at__lte=hasta,
        ).order_by("-created_at")

        estado_cita = self._clean(request.query_params.get("estado_cita"))
        canal = self._clean(request.query_params.get("canal_origen"))
        if estado_cita:
            citas = citas.filter(estado=estado_cita)
        if canal:
            citas = citas.filter(canal_origen=canal)

        historial = [
            {
                "id": str(c.id),
                "fecha": c.created_at.strftime("%Y-%m-%d"),
                "estado": c.estado,
                "canal": c.canal_origen,
                "motivo_visita": c.motivo_visita,
            }
            for c in citas
        ]

        distribucion_estados = [
            {"estado": x["estado"], "total": x["total"]}
            for x in citas.values("estado").annotate(total=Count("id")).order_by("-total")
        ]

        citas_por_mes = (
            citas.annotate(mes=TruncMonth("created_at"))
            .values("mes")
            .annotate(total=Count("id"))
            .order_by("mes")
        )
        citas_por_mes_fmt = [
            {"mes": item["mes"].strftime("%Y-%m") if item["mes"] else "N/A", "total": item["total"]}
            for item in citas_por_mes
        ]

        servicios_top = (
            CitaDetalle.objects.filter(cita__in=citas, servicio_catalogo__isnull=False)
            .values("servicio_catalogo__nombre")
            .annotate(total=Count("id"))
            .order_by("-total")[:5]
        )
        servicios_top_fmt = [{"servicio": s["servicio_catalogo__nombre"], "total": s["total"]} for s in servicios_top]

        primera = citas.last()
        ultima = citas.first()
        total_visitas = citas.count()
        completadas = citas.filter(estado=EstadoCita.FINALIZADA).count()
        canceladas = citas.filter(estado=EstadoCita.CANCELADA).count()
        no_show = citas.filter(estado=EstadoCita.NO_SHOW).count()
        tasa_completado = round((completadas / total_visitas) * 100, 2) if total_visitas > 0 else 0

        duraciones_horas = []
        for c in citas:
            if c.finalizada_at and c.llegada_real_at:
                delta = c.finalizada_at - c.llegada_real_at
                duraciones_horas.append(delta.total_seconds() / 3600)
        tiempo_promedio_atencion_horas = round(sum(duraciones_horas) / len(duraciones_horas), 2) if duraciones_horas else None

        return response.Response(
            {
                "vehiculo": {
                    "placa": vehiculo.placa,
                    "marca": vehiculo.marca,
                    "modelo": vehiculo.modelo,
                    "anio": vehiculo.anio,
                    "color": vehiculo.color,
                    "kilometraje_actual": vehiculo.kilometraje_actual,
                },
                "kpis": {
                    "total_visitas": total_visitas,
                    "ultima_visita": ultima.created_at.strftime("%Y-%m-%d") if ultima else "N/A",
                    "primera_visita": primera.created_at.strftime("%Y-%m-%d") if primera else "N/A",
                    "citas_finalizadas": completadas,
                    "citas_canceladas": canceladas,
                    "citas_no_show": no_show,
                    "tasa_completado_pct": tasa_completado,
                    "tiempo_promedio_atencion_horas": tiempo_promedio_atencion_horas,
                },
                "historial": historial,
                "distribucion_estados": distribucion_estados,
                "citas_por_mes": citas_por_mes_fmt,
                "servicios_top": servicios_top_fmt,
            }
        )

    @action(detail=False, methods=["get"])
    def presupuesto(self, request, **kwargs):
        empresa = request.user.empresa
        desde, hasta = self._get_fecha_range(request)
        estado = self._clean(request.query_params.get("estado_presupuesto"))
        placa = self._clean(request.query_params.get("placa"))

        presupuestos = PresupuestoCita.objects.filter(
            empresa=empresa,
            created_at__gte=desde,
            created_at__lte=hasta,
        ).select_related("cita", "cita__vehiculo")

        if estado:
            presupuestos = presupuestos.filter(estado=estado)
        if placa:
            presupuestos = presupuestos.filter(cita__vehiculo__placa__icontains=placa)

        total_pres = presupuestos.count()
        emitidos = presupuestos.exclude(estado=EstadoPresupuestoCita.BORRADOR).count()
        aprobados = presupuestos.filter(estado=EstadoPresupuestoCita.APROBADO).count()
        rechazados = presupuestos.filter(estado=EstadoPresupuestoCita.RECHAZADO).count()
        cerrados = presupuestos.filter(estado=EstadoPresupuestoCita.CERRADO).count()
        tasa_aprobacion = round((aprobados / emitidos) * 100, 2) if emitidos > 0 else 0
        monto_total = float(presupuestos.aggregate(total=Sum("total")).get("total") or 0)

        por_estado = [
            {"name": x["estado"], "value": x["total"]}
            for x in presupuestos.values("estado").annotate(total=Count("id")).order_by("-total")
        ]

        return response.Response(
            {
                "kpis": {
                    "presupuestos_total": total_pres,
                    "presupuestos_emitidos": emitidos,
                    "presupuestos_aprobados": aprobados,
                    "presupuestos_rechazados": rechazados,
                    "presupuestos_cerrados": cerrados,
                    "monto_total_presupuestado": monto_total,
                    "tasa_aprobacion": tasa_aprobacion,
                },
                "funnel": [
                    {"name": "Emitidos", "value": emitidos},
                    {"name": "Aprobados", "value": aprobados},
                    {"name": "Cerrados", "value": cerrados},
                ],
                "por_estado": por_estado,
            }
        )

    @action(detail=False, methods=["get"])
    def inventario(self, request, **kwargs):
        empresa = request.user.empresa
        desde, hasta = self._get_fecha_range(request)
        codigo = self._clean(request.query_params.get("codigo_servicio"))
        nombre = self._clean(request.query_params.get("nombre_servicio"))

        servicios = ServicioCatalogo.objects.filter(empresa=empresa)
        if codigo:
            servicios = servicios.filter(codigo__icontains=codigo)
        if nombre:
            servicios = servicios.filter(nombre__icontains=nombre)

        detalles = CitaDetalle.objects.filter(
            empresa=empresa,
            cita__created_at__gte=desde,
            cita__created_at__lte=hasta,
            servicio_catalogo__isnull=False,
        )
        demanda_por_servicio = {
            str(x["servicio_catalogo"]): x["total"]
            for x in detalles.values("servicio_catalogo").annotate(total=Count("id"))
        }

        datos = []
        for s in servicios:
            demanda = demanda_por_servicio.get(str(s.id), 0)
            datos.append(
                {
                    "nombre": s.nombre,
                    "codigo": s.codigo,
                    "demanda": demanda,
                    "precio_base": float(s.precio_base) if s.precio_base else 0,
                }
            )

        datos = sorted(datos, key=lambda x: x["demanda"], reverse=True)[:10]

        return response.Response({"top_servicios": datos})
