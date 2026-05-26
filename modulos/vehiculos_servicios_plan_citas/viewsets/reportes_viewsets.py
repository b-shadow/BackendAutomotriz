import logging
from datetime import datetime, timedelta

from django.db import models
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, TruncMonth
from rest_framework import response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from modulos.atencion_tecnica_ejecucion.models import EstadoPresupuestoCita, PresupuestoCita
from modulos.inventario_proveedores_administracion.models import (
    EstadoPagoTaller,
    EstadoSolicitudRepuesto,
    ItemInventario,
    PagoTaller,
    SolicitudRepuesto,
)
from modulos.vehiculos_servicios_plan_citas.models import (
    Cita,
    CitaDetalle,
    EstadoCita,
    EstadoPlanServicioDetalle,
    ServicioCatalogo,
    Vehiculo,
)

logger = logging.getLogger(__name__)


class ReportesViewSet(viewsets.ViewSet):
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

    def _duracion_horas_cita(self, cita):
        inicio = cita.llegada_real_at or cita.fecha_hora_inicio_programada
        fin = cita.vehiculo_devuelto_at or cita.finalizada_at or cita.fecha_hora_fin_programada
        if not inicio or not fin or fin < inicio:
            return 0
        return (fin - inicio).total_seconds() / 3600

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

        # CU39/CU42: comparativo de vehiculos en taller vs universo del sistema
        total_vehiculos_sistema = Vehiculo.objects.filter(empresa=empresa).count()
        vehiculos_en_taller = (
            Cita.objects.filter(
                empresa=empresa,
                estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO],
                vehiculo__isnull=False,
            )
            .values("vehiculo_id")
            .distinct()
            .count()
        )

        top_vehiculo_citas = (
            citas.filter(vehiculo__isnull=False)
            .values("vehiculo__placa", "vehiculo__marca", "vehiculo__modelo")
            .annotate(total=Count("id"))
            .order_by("-total")
            .first()
        )

        detalles_resueltos = (
            CitaDetalle.objects.filter(
                empresa=empresa,
                cita__in=citas,
                estado=EstadoPlanServicioDetalle.FINALIZADO,
                cita__vehiculo__isnull=False,
            )
            .values("cita__vehiculo__placa", "cita__vehiculo__marca", "cita__vehiculo__modelo")
            .annotate(total=Count("id"))
            .order_by("-total")
            .first()
        )

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
                    "vehiculos_en_taller": vehiculos_en_taller,
                    "vehiculos_total_sistema": total_vehiculos_sistema,
                    "ratio_vehiculos_en_taller_pct": round(
                        (vehiculos_en_taller / total_vehiculos_sistema) * 100, 2
                    )
                    if total_vehiculos_sistema > 0
                    else 0,
                },
                "ranking": {
                    "vehiculo_mas_citas": {
                        "placa": top_vehiculo_citas["vehiculo__placa"],
                        "vehiculo": f"{top_vehiculo_citas['vehiculo__marca']} {top_vehiculo_citas['vehiculo__modelo']}",
                        "total": top_vehiculo_citas["total"],
                    }
                    if top_vehiculo_citas
                    else None,
                    "vehiculo_mas_detalles_resueltos": {
                        "placa": detalles_resueltos["cita__vehiculo__placa"],
                        "vehiculo": f"{detalles_resueltos['cita__vehiculo__marca']} {detalles_resueltos['cita__vehiculo__modelo']}",
                        "total": detalles_resueltos["total"],
                    }
                    if detalles_resueltos
                    else None,
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
        top_n = int(self._clean(request.query_params.get("top_n")) or 10)

        if not placa:
            top_queryset = Cita.objects.filter(empresa=empresa, created_at__gte=desde, created_at__lte=hasta)
            top_queryset = self._apply_cita_filters(top_queryset, request)
            top_vehiculos = (
                top_queryset.values("vehiculo__placa", "vehiculo__marca", "vehiculo__modelo")
                .annotate(total_citas=Count("id"))
                .order_by("-total_citas")[:top_n]
            )

            top_detalles_resueltos = (
                CitaDetalle.objects.filter(
                    empresa=empresa,
                    cita__in=top_queryset,
                    cita__vehiculo__isnull=False,
                    estado=EstadoPlanServicioDetalle.FINALIZADO,
                )
                .values("cita__vehiculo__placa", "cita__vehiculo__marca", "cita__vehiculo__modelo")
                .annotate(total_resueltos=Count("id"))
                .order_by("-total_resueltos")[:top_n]
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

            top_solucionados = [
                {
                    "placa": v["cita__vehiculo__placa"],
                    "vehiculo": f"{v['cita__vehiculo__marca']} {v['cita__vehiculo__modelo']}",
                    "detalles_resueltos": v["total_resueltos"],
                }
                for v in top_detalles_resueltos
                if v["cita__vehiculo__placa"]
            ]

            return response.Response(
                {
                    "top_vehiculos": datos,
                    "top_vehiculos_detalles_resueltos": top_solucionados,
                }
            )

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
                "inicio_programado": c.fecha_hora_inicio_programada.strftime("%Y-%m-%d %H:%M")
                if c.fecha_hora_inicio_programada
                else None,
                "fin_programado": c.fecha_hora_fin_programada.strftime("%Y-%m-%d %H:%M")
                if c.fecha_hora_fin_programada
                else None,
                "estado": c.estado,
                "canal": c.canal_origen,
                "motivo_visita": c.motivo_visita,
            }
            for c in citas
        ]

        detalles_qs = CitaDetalle.objects.filter(cita__in=citas).select_related("servicio_catalogo", "cita")
        detalles_historial = [
            {
                "cita_id": str(d.cita_id),
                "fecha_cita": d.cita.fecha_hora_inicio_programada.strftime("%Y-%m-%d")
                if d.cita and d.cita.fecha_hora_inicio_programada
                else None,
                "servicio": d.servicio_catalogo.nombre if d.servicio_catalogo else "Servicio sin catalogo",
                "estado_detalle": d.estado,
                "tiempo_estandar_min": d.tiempo_estandar_min,
                "precio_referencial": float(d.precio_referencial or 0),
                "observaciones": d.observaciones,
            }
            for d in detalles_qs.order_by("-cita__fecha_hora_inicio_programada", "-created_at")
        ]

        distribucion_estados = [
            {"estado": x["estado"], "total": x["total"]}
            for x in citas.values("estado").annotate(total=Count("id")).order_by("-total")
        ]

        citas_por_mes = (
            citas.annotate(mes=TruncMonth("created_at")).values("mes").annotate(total=Count("id")).order_by("mes")
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

        duraciones_horas = [self._duracion_horas_cita(c) for c in citas]
        duraciones_horas = [d for d in duraciones_horas if d > 0]
        tiempo_total_taller_horas = round(sum(duraciones_horas), 2) if duraciones_horas else 0
        tiempo_promedio_atencion_horas = round(sum(duraciones_horas) / len(duraciones_horas), 2) if duraciones_horas else None

        total_detalles = detalles_qs.count()
        detalles_resueltos = detalles_qs.filter(estado=EstadoPlanServicioDetalle.FINALIZADO).count()
        tasa_detalles_resueltos = round((detalles_resueltos / total_detalles) * 100, 2) if total_detalles > 0 else 0

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
                    "tiempo_total_taller_horas": tiempo_total_taller_horas,
                    "detalles_totales": total_detalles,
                    "detalles_resueltos": detalles_resueltos,
                    "tasa_detalles_resueltos_pct": tasa_detalles_resueltos,
                },
                "historial": historial,
                "detalles_historial": detalles_historial,
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

    @action(detail=False, methods=["get"])
    def dashboard_kpis(self, request, **kwargs):
        empresa = request.user.empresa
        rol = request.user.rol.nombre if request.user and request.user.rol else "USUARIO"
        hoy = datetime.now().date()

        data = {
            "rol": rol,
            "hoy": hoy.isoformat(),
            "kpis": {},
        }

        citas_hoy = Cita.objects.filter(empresa=empresa, fecha_hora_inicio_programada__date=hoy).count()
        en_proceso = Cita.objects.filter(empresa=empresa, estado=EstadoCita.EN_PROCESO).count()
        data["kpis"]["citas_hoy"] = citas_hoy
        data["kpis"]["vehiculos_en_proceso"] = en_proceso

        if rol in ["ADMIN", "ADMINISTRATIVO"]:
            pagos_hoy = (
                PagoTaller.objects.filter(empresa=empresa, recibido_at__date=hoy, estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO])
                .aggregate(total=Sum("monto_total"))
                .get("total")
                or 0
            )
            pendientes_pago = PresupuestoCita.objects.filter(empresa=empresa, estado=EstadoPresupuestoCita.APROBADO).count()
            data["kpis"]["ingresos_hoy"] = float(pagos_hoy)
            data["kpis"]["presupuestos_pendientes_pago"] = pendientes_pago

        if rol in ["ADMIN", "ALMACENERO"]:
            stock_bajo = ItemInventario.objects.filter(empresa=empresa, activo=True, stock_actual__lte=models.F("stock_minimo")).count()
            solicitudes_pendientes = SolicitudRepuesto.objects.filter(
                empresa=empresa,
                estado__in=[EstadoSolicitudRepuesto.CREADA, EstadoSolicitudRepuesto.APROBADA_POR_ASESOR, EstadoSolicitudRepuesto.EN_REVISION_ALMACEN],
            ).count()
            data["kpis"]["items_stock_bajo"] = stock_bajo
            data["kpis"]["solicitudes_pendientes"] = solicitudes_pendientes

        return response.Response(data)
