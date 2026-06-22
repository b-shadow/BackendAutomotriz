import logging
from datetime import datetime, timedelta

from django.db import models
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from rest_framework import response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from modulos.atencion_tecnica_ejecucion.models import (
    AvanceVehiculo,
    EstadoOrdenTrabajoDetalle,
    EstadoOrdenTrabajoGlobal,
    EstadoPresupuestoCita,
    OrdenTrabajoDetalle,
    OrdenTrabajoGlobal,
    PresupuestoCita,
    RecepcionVehiculo,
)
from modulos.administracion_acceso_configuracion.models import Usuario
from modulos.inventario_proveedores_administracion.models import (
    CompraDetalle,
    EstadoCompra,
    EstadoPagoTaller,
    EstadoSolicitudRepuesto,
    EstadoSolicitudRepuestoDetalle,
    EstadoVentaMostrador,
    Factura,
    ItemInventario,
    MovimientoInventario,
    PagoTaller,
    SolicitudRepuesto,
    SolicitudRepuestoDetalle,
    VentaMostrador,
    Compra,
    Proveedor
)
from modulos.vehiculos_servicios_plan_citas.models import (
    Cita,
    CitaDetalle,
    EstadoCita,
    EstadoPlanServicioDetalle,
    PlanServicioDetalle,
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

    def _rol_dashboard(self, user):
        rol = user.rol.nombre if user and getattr(user, "rol", None) else "USUARIO"
        return (rol or "USUARIO").strip().upper()

    def _kpi(self, key, label, value, format_type="number", tone="neutral"):
        return {
            "key": key,
            "label": label,
            "value": value,
            "format": format_type,
            "tone": tone,
        }

    def _section(self, section_id, title, description, kpis=None, charts=None, tables=None):
        return {
            "id": section_id,
            "title": title,
            "description": description,
            "kpis": kpis or [],
            "charts": charts or [],
            "tables": tables or [],
        }

    def _chart(self, chart_id, chart_type, title, data, x_key=None, y_key=None, series=None):
        payload = {
            "id": chart_id,
            "type": chart_type,
            "title": title,
            "data": data or [],
        }
        if x_key:
            payload["xKey"] = x_key
        if y_key:
            payload["yKey"] = y_key
        if series:
            payload["series"] = series
        return payload

    def _table(self, table_id, title, columns, rows):
        return {
            "id": table_id,
            "title": title,
            "columns": columns,
            "rows": rows or [],
        }

    def _serie_ultimos_dias(self, queryset, date_field, *, days=7, sum_field=None):
        inicio = timezone.localdate() - timedelta(days=days - 1)
        filtros = {f"{date_field}__date__gte": inicio}
        base = queryset.filter(**filtros).annotate(fecha=TruncDate(date_field)).values("fecha")
        if sum_field:
            filas = base.annotate(total=Sum(sum_field)).order_by("fecha")
        else:
            filas = base.annotate(total=Count("id")).order_by("fecha")

        valores = {
            fila["fecha"]: float(fila["total"] or 0) if sum_field else fila["total"]
            for fila in filas
            if fila["fecha"]
        }
        salida = []
        for offset in range(days):
            fecha = inicio + timedelta(days=offset)
            salida.append(
                {
                    "fecha": fecha.strftime("%Y-%m-%d"),
                    "total": valores.get(fecha, 0),
                }
            )
        return salida

    def _serie_ultimos_meses(self, datasets, *, months=6):
        hoy = timezone.localdate()
        periodo = []
        year = hoy.year
        month = hoy.month

        for _ in range(months):
            periodo.append((year, month))
            month -= 1
            if month == 0:
                month = 12
                year -= 1

        periodo.reverse()
        salida = []

        agregados = {}
        for key, spec in datasets.items():
            queryset = spec["queryset"]
            date_field = spec["date_field"]
            sum_field = spec.get("sum_field")

            inicio_year, inicio_month = periodo[0]
            filtros = {
                f"{date_field}__year__gte": inicio_year,
            }
            base = queryset.filter(**filtros).annotate(mes=TruncMonth(date_field)).values("mes")
            if sum_field:
                filas = base.annotate(total=Sum(sum_field)).order_by("mes")
                agregados[key] = {
                    (fila["mes"].year, fila["mes"].month): float(fila["total"] or 0)
                    for fila in filas
                    if fila["mes"] and (fila["mes"].year, fila["mes"].month) in periodo
                }
            else:
                filas = base.annotate(total=Count("id")).order_by("mes")
                agregados[key] = {
                    (fila["mes"].year, fila["mes"].month): fila["total"]
                    for fila in filas
                    if fila["mes"] and (fila["mes"].year, fila["mes"].month) in periodo
                }

        for year, month in periodo:
            fila = {
                "mes": f"{year}-{month:02d}",
            }
            for key in datasets.keys():
                fila[key] = agregados.get(key, {}).get((year, month), 0)
            salida.append(fila)

        return salida

    def _flatten_kpis(self, sections):
        flat = {}
        for section in sections:
            for kpi in section.get("kpis", []):
                flat[kpi["key"]] = kpi["value"]
        return flat

    def _dashboard_usuario(self, request, empresa, hoy):
        citas_usuario = Cita.objects.filter(empresa=empresa, cliente=request.user)
        vehiculos_usuario = Vehiculo.objects.filter(empresa=empresa, propietario=request.user)
        presupuestos_usuario = PresupuestoCita.objects.filter(empresa=empresa, cita__cliente=request.user)
        plan_detalles_usuario = PlanServicioDetalle.objects.filter(
            empresa=empresa,
            plan_servicio__vehiculo__propietario=request.user,
        )
        pagos_usuario = PagoTaller.objects.filter(
            empresa=empresa,
            cita__cliente=request.user,
        ).exclude(estado=EstadoPagoTaller.ANULADO)
        solicitudes_usuario = SolicitudRepuesto.objects.filter(
            empresa=empresa,
            cita__cliente=request.user,
        )
        solicitud_detalles_usuario = SolicitudRepuestoDetalle.objects.filter(
            empresa=empresa,
            solicitud__cita__cliente=request.user,
        )
        serie_usuario_actividad = self._serie_ultimos_meses(
            {
                "citas": {
                    "queryset": citas_usuario,
                    "date_field": "fecha_hora_inicio_programada",
                },
                "presupuestos": {
                    "queryset": presupuestos_usuario,
                    "date_field": "created_at",
                },
            },
            months=6,
        )

        proximas_citas = citas_usuario.filter(
            fecha_hora_inicio_programada__date__gte=hoy,
            estado__in=[
                EstadoCita.PENDIENTE_APROBACION,
                EstadoCita.PROGRAMADA,
                EstadoCita.EN_ESPERA_INGRESO,
                EstadoCita.EN_PROCESO,
            ],
        )
        vehiculos_taller = citas_usuario.filter(
            estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO],
            vehiculo__isnull=False,
        ).values("vehiculo_id").distinct().count()
        presupuestos_pendientes = presupuestos_usuario.filter(
            estado__in=[EstadoPresupuestoCita.COMUNICADO, EstadoPresupuestoCita.AJUSTADO]
        ).count()
        pagos_pendientes = pagos_usuario.filter(
            estado__in=[
                EstadoPagoTaller.PENDIENTE,
                EstadoPagoTaller.PROCESANDO,
                EstadoPagoTaller.REGISTRADO,
            ]
        ).count()
        avances_visibles = AvanceVehiculo.objects.filter(
            empresa=empresa,
            cita__cliente=request.user,
            visible_cliente=True,
        )

        agenda_rows = [
            {
                "fecha": cita.fecha_hora_inicio_programada.strftime("%Y-%m-%d %H:%M"),
                "vehiculo": f"{cita.vehiculo.marca} {cita.vehiculo.modelo}" if cita.vehiculo else "Sin vehículo",
                "placa": cita.vehiculo.placa if cita.vehiculo else "-",
                "estado": cita.estado,
            }
            for cita in proximas_citas.select_related("vehiculo").order_by("fecha_hora_inicio_programada")[:5]
        ]
        taller_rows = [
            {
                "placa": cita.vehiculo.placa if cita.vehiculo else "-",
                "vehiculo": f"{cita.vehiculo.marca} {cita.vehiculo.modelo}" if cita.vehiculo else "Sin vehículo",
                "estado": cita.estado,
                "avance": (
                    avances_visibles.filter(cita=cita).order_by("-created_at").values_list("estado_nuevo", flat=True).first()
                    or "Sin actualización"
                ),
            }
            for cita in citas_usuario.filter(
                estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO]
            ).select_related("vehiculo").order_by("-updated_at")[:5]
        ]

        return [
            self._section(
                "usuario_resumen",
                "Mi actividad",
                "Resumen personal de vehículos, citas y pagos.",
                kpis=[
                    self._kpi("mis_vehiculos", "Mis vehículos", vehiculos_usuario.count()),
                    self._kpi("mis_citas_proximas", "Citas próximas", proximas_citas.count()),
                    self._kpi("mis_vehiculos_en_taller", "Vehículos en taller", vehiculos_taller, tone="warning"),
                    self._kpi(
                        "mis_servicios_plan_activos",
                        "Servicios de plan activos",
                        plan_detalles_usuario.filter(
                            estado__in=[
                                EstadoPlanServicioDetalle.PENDIENTE,
                                EstadoPlanServicioDetalle.PROGRAMADO,
                                EstadoPlanServicioDetalle.EN_PROCESO,
                                EstadoPlanServicioDetalle.RECOMENDADO,
                            ]
                        ).count(),
                    ),
                    self._kpi("mis_presupuestos_pendientes", "Presupuestos por responder", presupuestos_pendientes, tone="warning"),
                    self._kpi("mis_pagos_pendientes", "Pagos pendientes", pagos_pendientes, tone="danger"),
                    self._kpi(
                        "mis_solicitudes_repuesto_activas",
                        "Solicitudes de repuesto activas",
                        solicitudes_usuario.exclude(
                            estado__in=[
                                EstadoSolicitudRepuesto.ENTREGADA,
                                EstadoSolicitudRepuesto.CERRADA,
                                EstadoSolicitudRepuesto.RECHAZADA_POR_ASESOR,
                            ]
                        ).count(),
                        tone="warning",
                    ),
                    self._kpi(
                        "mis_items_repuesto_pendientes",
                        "Items de repuesto pendientes",
                        solicitud_detalles_usuario.exclude(
                            estado__in=[
                                EstadoSolicitudRepuestoDetalle.ENTREGADO,
                                EstadoSolicitudRepuestoDetalle.CANCELADO,
                            ]
                        ).count(),
                        tone="warning",
                    ),
                ],
                charts=[
                    self._chart(
                        "mis_citas_estado",
                        "pie",
                        "Estado de mis citas",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in citas_usuario.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "mis_actividad_6m",
                        "line",
                        "Mis citas y presupuestos por mes",
                        serie_usuario_actividad,
                        x_key="mes",
                        series=[
                            {"key": "citas", "label": "Citas"},
                            {"key": "presupuestos", "label": "Presupuestos"},
                        ],
                    ),
                    self._chart(
                        "mis_planes_estado",
                        "bar",
                        "Estado de servicios de mi plan",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in plan_detalles_usuario.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "mis_repuestos_estado",
                        "bar",
                        "Estado de mis items de repuesto",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in solicitud_detalles_usuario.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "mis_pagos_estado",
                        "pie",
                        "Estado de mis pagos",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in pagos_usuario.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                ],
                tables=[
                    self._table(
                        "mis_proximas_citas",
                        "Próximas citas",
                        ["Fecha", "Vehículo", "Placa", "Estado"],
                        agenda_rows,
                    ),
                    self._table(
                        "mis_vehiculos_taller",
                        "Vehículos actualmente en taller",
                        ["Placa", "Vehículo", "Estado", "Último avance"],
                        taller_rows,
                    ),
                ],
            )
        ]

    def _dashboard_asesor(self, empresa, hoy):
        citas = Cita.objects.filter(empresa=empresa)
        presupuestos = PresupuestoCita.objects.filter(empresa=empresa)
        ordenes = OrdenTrabajoGlobal.objects.filter(empresa=empresa)
        ordenes_detalle = OrdenTrabajoDetalle.objects.filter(empresa=empresa)
        planes_detalle = PlanServicioDetalle.objects.filter(empresa=empresa)
        recepciones = RecepcionVehiculo.objects.filter(empresa=empresa)
        solicitudes = SolicitudRepuesto.objects.filter(empresa=empresa)
        solicitud_detalles = SolicitudRepuestoDetalle.objects.filter(empresa=empresa)
        serie_asesor_operacion = self._serie_ultimos_meses(
            {
                "citas": {
                    "queryset": citas,
                    "date_field": "fecha_hora_inicio_programada",
                },
                "recepciones": {
                    "queryset": recepciones,
                    "date_field": "fecha_recepcion",
                },
            },
            months=6,
        )

        citas_activas = citas.filter(
            estado__in=[EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO]
        )
        vehiculos_en_taller_rows = [
            {
                "placa": cita.vehiculo.placa if cita.vehiculo else "-",
                "vehiculo": f"{cita.vehiculo.marca} {cita.vehiculo.modelo}" if cita.vehiculo else "Sin vehículo",
                "cliente": cita.cliente.get_full_name() if cita.cliente else "-",
                "estado": cita.estado,
            }
            for cita in citas.filter(
                estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO]
            ).select_related("vehiculo", "cliente").order_by("fecha_hora_inicio_programada")[:8]
        ]

        return [
            self._section(
                "asesor_operacion",
                "Operación del taller",
                "Citas, recepciones, presupuestos y órdenes activas.",
                kpis=[
                    self._kpi("citas_hoy", "Citas de hoy", citas.filter(fecha_hora_inicio_programada__date=hoy).count()),
                    self._kpi("citas_pendientes_aprobacion", "Pendientes de aprobación", citas.filter(estado=EstadoCita.PENDIENTE_APROBACION).count(), tone="warning"),
                    self._kpi("vehiculos_en_taller", "Vehículos en taller", citas.filter(estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO], vehiculo__isnull=False).values("vehiculo_id").distinct().count()),
                    self._kpi("recepciones_hoy", "Recepciones de hoy", recepciones.filter(fecha_recepcion__date=hoy).count()),
                    self._kpi("recepciones_pendientes_entrega", "Recepciones sin entrega", recepciones.filter(fecha_recogida__isnull=True).count(), tone="warning"),
                    self._kpi(
                        "servicios_plan_urgentes",
                        "Servicios urgentes del plan",
                        planes_detalle.filter(
                            estado__in=[
                                EstadoPlanServicioDetalle.PENDIENTE,
                                EstadoPlanServicioDetalle.PROGRAMADO,
                                EstadoPlanServicioDetalle.EN_PROCESO,
                                EstadoPlanServicioDetalle.RECOMENDADO,
                            ],
                            prioridad__in=["ALTA", "URGENTE"],
                        ).count(),
                        tone="danger",
                    ),
                    self._kpi(
                        "solicitudes_esperando_asesor",
                        "Solicitudes esperando asesor",
                        solicitudes.filter(estado=EstadoSolicitudRepuesto.CREADA).count(),
                        tone="warning",
                    ),
                    self._kpi(
                        "repuestos_en_almacen",
                        "Solicitudes en almacen",
                        solicitudes.filter(
                            estado__in=[
                                EstadoSolicitudRepuesto.APROBADA_POR_ASESOR,
                                EstadoSolicitudRepuesto.EN_REVISION_ALMACEN,
                                EstadoSolicitudRepuesto.PARCIALMENTE_DISPONIBLE,
                            ]
                        ).count(),
                        tone="warning",
                    ),
                    self._kpi("presupuestos_por_responder", "Presupuestos por responder", presupuestos.filter(estado__in=[EstadoPresupuestoCita.COMUNICADO, EstadoPresupuestoCita.AJUSTADO]).count(), tone="warning"),
                    self._kpi("ordenes_abiertas", "Órdenes abiertas", ordenes.filter(estado__in=[EstadoOrdenTrabajoGlobal.ABIERTA, EstadoOrdenTrabajoGlobal.ASIGNADA, EstadoOrdenTrabajoGlobal.EN_PROCESO, EstadoOrdenTrabajoGlobal.PAUSADA]).count()),
                ],
                charts=[
                    self._chart(
                        "citas_semana_asesor",
                        "line",
                        "Citas programadas en los últimos 7 días",
                        self._serie_ultimos_dias(citas, "fecha_hora_inicio_programada"),
                        x_key="fecha",
                        y_key="total",
                    ),
                    self._chart(
                        "presupuestos_estado_asesor",
                        "pie",
                        "Estado de presupuestos",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in presupuestos.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "solicitudes_estado_asesor",
                        "pie",
                        "Estado de solicitudes de repuesto",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in solicitudes.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "citas_vs_recepciones_asesor",
                        "line",
                        "Citas vs recepciones por mes",
                        serie_asesor_operacion,
                        x_key="mes",
                        series=[
                            {"key": "citas", "label": "Citas"},
                            {"key": "recepciones", "label": "Recepciones"},
                        ],
                    ),
                ],
                tables=[
                    self._table(
                        "vehiculos_taller_asesor",
                        "Vehículos actualmente en taller",
                        ["Placa", "Vehículo", "Cliente", "Estado"],
                        vehiculos_en_taller_rows,
                    ),
                ],
            ),
            self._section(
                "asesor_demanda",
                "Demanda de servicio",
                "Servicios y vehículos con mayor actividad.",
                charts=[
                    self._chart(
                        "top_vehiculos_asesor",
                        "bar",
                        "Vehículos con más citas",
                        [
                            {
                                "name": fila["vehiculo__placa"] or "Sin placa",
                                "value": fila["total"],
                            }
                            for fila in citas.filter(vehiculo__isnull=False)
                            .values("vehiculo__placa")
                            .annotate(total=Count("id"))
                            .order_by("-total")[:6]
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "estado_ordenes_detalle_asesor",
                        "bar",
                        "Estado de servicios en ordenes de trabajo",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in ordenes_detalle.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "prioridad_planes_asesor",
                        "bar",
                        "Prioridad de servicios del plan",
                        [
                            {"name": fila["prioridad"], "value": fila["total"]}
                            for fila in planes_detalle.values("prioridad").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "top_servicios_asesor",
                        "bar",
                        "Servicios mas demandados",
                        [
                            {
                                "name": fila["servicio_catalogo__nombre"] or "Servicio",
                                "value": fila["total"],
                            }
                            for fila in planes_detalle.values("servicio_catalogo__nombre")
                            .annotate(total=Count("id"))
                            .order_by("-total")[:6]
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "solicitudes_detalle_asesor",
                        "bar",
                        "Estado de items solicitados",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in solicitud_detalles.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                ],
                tables=[
                    self._table(
                        "proximas_citas_asesor",
                        "Próximas citas",
                        ["Fecha", "Placa", "Vehículo", "Canal"],
                        [
                            {
                                "fecha": cita.fecha_hora_inicio_programada.strftime("%Y-%m-%d %H:%M"),
                                "placa": cita.vehiculo.placa if cita.vehiculo else "-",
                                "vehiculo": f"{cita.vehiculo.marca} {cita.vehiculo.modelo}" if cita.vehiculo else "Sin vehículo",
                                "canal": cita.canal_origen,
                            }
                            for cita in citas_activas.select_related("vehiculo").order_by("fecha_hora_inicio_programada")[:6]
                        ],
                    ),
                ],
            ),
        ]

    def _dashboard_mecanico(self, request, empresa, hoy):
        detalles = OrdenTrabajoDetalle.objects.filter(empresa=empresa, mecanico_asignado=request.user)
        ordenes = OrdenTrabajoGlobal.objects.filter(empresa=empresa, mecanicos_asignados__mecanico=request.user).distinct()
        solicitudes = SolicitudRepuesto.objects.filter(empresa=empresa, solicitado_por=request.user)
        solicitudes_detalle = SolicitudRepuestoDetalle.objects.filter(
            empresa=empresa,
            solicitud__solicitado_por=request.user,
        )
        planes_detalle = PlanServicioDetalle.objects.filter(
            empresa=empresa,
            ordenes_detalles__mecanico_asignado=request.user,
        ).distinct()

        tareas_activas = detalles.filter(
            estado__in=[
                EstadoOrdenTrabajoDetalle.POR_HACER,
                EstadoOrdenTrabajoDetalle.EN_PROCESO,
                EstadoOrdenTrabajoDetalle.PAUSADO,
            ]
        )
        serie_mecanico_carga = self._serie_ultimos_meses(
            {
                "asignados": {
                    "queryset": detalles,
                    "date_field": "created_at",
                },
                "finalizados": {
                    "queryset": detalles.filter(
                        estado=EstadoOrdenTrabajoDetalle.FINALIZADO,
                        fin_real__isnull=False,
                    ),
                    "date_field": "fin_real",
                },
            },
            months=6,
        )

        return [
            self._section(
                "mecanico_tareas",
                "Mis tareas técnicas",
                "Carga de trabajo, avance y repuestos solicitados.",
                kpis=[
                    self._kpi("ordenes_asignadas_activas", "Órdenes asignadas", ordenes.filter(estado__in=[EstadoOrdenTrabajoGlobal.ASIGNADA, EstadoOrdenTrabajoGlobal.EN_PROCESO, EstadoOrdenTrabajoGlobal.PAUSADA]).count()),
                    self._kpi("detalles_pendientes", "Servicios por hacer", detalles.filter(estado=EstadoOrdenTrabajoDetalle.POR_HACER).count()),
                    self._kpi("detalles_en_proceso", "Servicios en proceso", detalles.filter(estado=EstadoOrdenTrabajoDetalle.EN_PROCESO).count(), tone="warning"),
                    self._kpi("detalles_finalizados_hoy", "Servicios finalizados hoy", detalles.filter(fin_real__date=hoy, estado=EstadoOrdenTrabajoDetalle.FINALIZADO).count(), tone="success"),
                    self._kpi(
                        "servicios_alta_prioridad",
                        "Servicios de alta prioridad",
                        detalles.filter(
                            estado__in=[
                                EstadoOrdenTrabajoDetalle.POR_HACER,
                                EstadoOrdenTrabajoDetalle.EN_PROCESO,
                                EstadoOrdenTrabajoDetalle.PAUSADO,
                            ],
                            prioridad__in=["ALTA", "URGENTE"],
                        ).count(),
                        tone="danger",
                    ),
                    self._kpi(
                        "horas_estimadas_pendientes",
                        "Horas estimadas pendientes",
                        round(float((tareas_activas.aggregate(total=Sum("tiempo_estandar_min")).get("total") or 0)) / 60, 2),
                    ),
                    self._kpi("solicitudes_repuesto_abiertas", "Solicitudes de repuesto abiertas", solicitudes.exclude(estado__in=[EstadoSolicitudRepuesto.ENTREGADA, EstadoSolicitudRepuesto.CERRADA, EstadoSolicitudRepuesto.RECHAZADA_POR_ASESOR]).count(), tone="warning"),
                    self._kpi(
                        "items_repuesto_pendientes",
                        "Items de repuesto pendientes",
                        solicitudes_detalle.exclude(
                            estado__in=[
                                EstadoSolicitudRepuestoDetalle.ENTREGADO,
                                EstadoSolicitudRepuestoDetalle.CANCELADO,
                            ]
                        ).count(),
                        tone="warning",
                    ),
                    self._kpi(
                        "items_repuesto_sin_stock",
                        "Items solicitados sin stock",
                        solicitudes_detalle.filter(estado=EstadoSolicitudRepuestoDetalle.SIN_STOCK).count(),
                        tone="danger",
                    ),
                ],
                charts=[
                    self._chart(
                        "mecanico_estado_tareas",
                        "pie",
                        "Estado de mis servicios",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in detalles.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "mecanico_estado_repuestos",
                        "pie",
                        "Estado de items de repuesto solicitados",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in solicitudes_detalle.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "mecanico_carga_6m",
                        "line",
                        "Servicios asignados vs finalizados por mes",
                        serie_mecanico_carga,
                        x_key="mes",
                        series=[
                            {"key": "asignados", "label": "Asignados"},
                            {"key": "finalizados", "label": "Finalizados"},
                        ],
                    ),
                    self._chart(
                        "mecanico_prioridad_tareas",
                        "bar",
                        "Prioridad de mis servicios activos",
                        [
                            {"name": fila["prioridad"], "value": fila["total"]}
                            for fila in tareas_activas.values("prioridad").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "mecanico_top_servicios",
                        "bar",
                        "Servicios tecnicos mas asignados",
                        [
                            {
                                "name": fila["servicio_catalogo__nombre"] or "Servicio",
                                "value": fila["total"],
                            }
                            for fila in detalles.values("servicio_catalogo__nombre")
                            .annotate(total=Count("id"))
                            .order_by("-total")[:6]
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                ],
                tables=[
                    self._table(
                        "mecanico_tareas_activas",
                        "Servicios activos asignados",
                        ["Vehículo", "Placa", "Servicio", "Prioridad", "Estado"],
                        [
                            {
                                "vehiculo": f"{detalle.orden_global.cita.vehiculo.marca} {detalle.orden_global.cita.vehiculo.modelo}" if detalle.orden_global and detalle.orden_global.cita and detalle.orden_global.cita.vehiculo else "Sin vehículo",
                                "placa": detalle.orden_global.cita.vehiculo.placa if detalle.orden_global and detalle.orden_global.cita and detalle.orden_global.cita.vehiculo else "-",
                                "servicio": detalle.servicio_catalogo.nombre if detalle.servicio_catalogo else "Servicio manual",
                                "prioridad": detalle.prioridad,
                                "estado": detalle.estado,
                            }
                            for detalle in tareas_activas.select_related(
                                "orden_global__cita__vehiculo",
                                "servicio_catalogo",
                            ).order_by("-prioridad", "orden_visual")[:8]
                        ],
                    ),
                    self._table(
                        "mecanico_plan_detalles",
                        "Servicios del plan vinculados",
                        ["Servicio", "Estado", "Prioridad", "Tiempo estandar"],
                        [
                            {
                                "servicio": detalle.servicio_catalogo.nombre if detalle.servicio_catalogo else "Servicio manual",
                                "estado": detalle.estado,
                                "prioridad": detalle.prioridad,
                                "tiempo_estandar": detalle.tiempo_estandar_min,
                            }
                            for detalle in planes_detalle.select_related("servicio_catalogo").order_by("-prioridad", "-updated_at")[:8]
                        ],
                    ),
                ],
            )
        ]

    def _dashboard_administrativo(self, empresa, hoy):
        pagos = PagoTaller.objects.filter(empresa=empresa).exclude(estado=EstadoPagoTaller.ANULADO)
        ventas = VentaMostrador.objects.filter(empresa=empresa)
        compras = Compra.objects.filter(empresa=empresa)
        facturas = Factura.objects.filter(empresa=empresa)
        inicio_mes = hoy.replace(day=1)
        serie_finanzas_mensual = self._serie_ultimos_meses(
            {
                "ingresos": {
                    "queryset": pagos.filter(estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO]),
                    "date_field": "recibido_at",
                    "sum_field": "monto_total",
                },
                "compras": {
                    "queryset": compras.filter(estado=EstadoCompra.CONFIRMADA),
                    "date_field": "fecha_compra",
                    "sum_field": "total",
                },
            },
            months=6,
        )
        serie_documentos_mensual = self._serie_ultimos_meses(
            {
                "ventas": {
                    "queryset": ventas.filter(estado=EstadoVentaMostrador.CONFIRMADA),
                    "date_field": "created_at",
                },
                "facturas": {
                    "queryset": facturas,
                    "date_field": "created_at",
                },
            },
            months=6,
        )

        return [
            self._section(
                "administrativo_finanzas",
                "Caja y facturación",
                "Cobros del taller, ventas, facturas y compras.",
                kpis=[
                    self._kpi("ingresos_hoy", "Ingresos hoy", float(pagos.filter(recibido_at__date=hoy, estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO]).aggregate(total=Sum("monto_total")).get("total") or 0), format_type="currency", tone="success"),
                    self._kpi("ingresos_mes", "Ingresos del mes", float(pagos.filter(recibido_at__date__gte=inicio_mes, estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO]).aggregate(total=Sum("monto_total")).get("total") or 0), format_type="currency"),
                    self._kpi("pagos_pendientes", "Pagos pendientes", pagos.filter(estado__in=[EstadoPagoTaller.PENDIENTE, EstadoPagoTaller.PROCESANDO, EstadoPagoTaller.REGISTRADO]).count(), tone="warning"),
                    self._kpi("ventas_mostrador_mes", "Ventas mostrador del mes", ventas.filter(created_at__date__gte=inicio_mes, estado=EstadoVentaMostrador.CONFIRMADA).count()),
                    self._kpi("facturas_emitidas_mes", "Facturas emitidas", facturas.filter(created_at__date__gte=inicio_mes).count()),
                    self._kpi(
                        "gasto_compras_mes",
                        "Gasto en compras del mes",
                        float(
                            compras.filter(created_at__date__gte=inicio_mes, estado=EstadoCompra.CONFIRMADA)
                            .aggregate(total=Sum("total"))
                            .get("total")
                            or 0
                        ),
                        format_type="currency",
                    ),
                ],
                charts=[
                    self._chart(
                        "ingresos_7d_admin",
                        "line",
                        "Cobros registrados últimos 7 días",
                        self._serie_ultimos_dias(
                            pagos.filter(estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO]),
                            "recibido_at",
                            sum_field="monto_total",
                        ),
                        x_key="fecha",
                        y_key="total",
                    ),
                    self._chart(
                        "pagos_estado_admin",
                        "pie",
                        "Estado de pagos",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in pagos.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "flujo_finanzas_6m_admin",
                        "bar",
                        "Ingresos vs compras por mes",
                        serie_finanzas_mensual,
                        x_key="mes",
                        series=[
                            {"key": "ingresos", "label": "Ingresos"},
                            {"key": "compras", "label": "Compras"},
                        ],
                    ),
                    self._chart(
                        "documentos_6m_admin",
                        "line",
                        "Ventas y facturas por mes",
                        serie_documentos_mensual,
                        x_key="mes",
                        series=[
                            {"key": "ventas", "label": "Ventas"},
                            {"key": "facturas", "label": "Facturas"},
                        ],
                    ),
                    self._chart(
                        "pagos_metodo_admin",
                        "bar",
                        "Cobros por metodo de pago",
                        [
                            {"name": fila["metodo_pago"] or "Sin metodo", "value": fila["total"]}
                            for fila in pagos.values("metodo_pago").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "ventas_estado_admin",
                        "pie",
                        "Estado de ventas de mostrador",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in ventas.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                ],
                tables=[
                    self._table(
                        "pagos_recientes_admin",
                        "Cobros recientes",
                        ["Origen", "Estado", "Monto", "Método", "Fecha"],
                        [
                            {
                                "origen": "Cita" if pago.cita_id else "Venta",
                                "estado": pago.estado,
                                "monto": float(pago.monto_total or 0),
                                "metodo": pago.metodo_pago,
                                "fecha": (
                                    (pago.recibido_at or pago.created_at).strftime("%Y-%m-%d %H:%M")
                                    if (pago.recibido_at or pago.created_at)
                                    else "-"
                                ),
                            }
                            for pago in pagos.order_by("-created_at")[:8]
                        ],
                    ),
                ],
            )
        ]

    def _dashboard_almacenero(self, empresa, hoy):
        items = ItemInventario.objects.filter(empresa=empresa, activo=True)
        solicitudes = SolicitudRepuesto.objects.filter(empresa=empresa)
        solicitud_detalles = SolicitudRepuestoDetalle.objects.filter(empresa=empresa)
        compras = Compra.objects.filter(empresa=empresa)
        movimientos = MovimientoInventario.objects.filter(empresa=empresa)
        inicio_mes = hoy.replace(day=1)
        serie_almacen_flujo = self._serie_ultimos_meses(
            {
                "compras": {
                    "queryset": compras.filter(estado=EstadoCompra.CONFIRMADA),
                    "date_field": "fecha_compra",
                },
                "movimientos": {
                    "queryset": movimientos,
                    "date_field": "created_at",
                },
            },
            months=6,
        )

        return [
            self._section(
                "almacen_control",
                "Almacén e inventario",
                "Stock crítico, solicitudes y compras del almacén.",
                kpis=[
                    self._kpi("items_stock_bajo", "Items con stock bajo", items.filter(stock_actual__lte=models.F("stock_minimo")).count(), tone="danger"),
                    self._kpi("items_sin_stock", "Items sin stock", items.filter(stock_actual__lte=0).count(), tone="danger"),
                    self._kpi("solicitudes_pendientes_almacen", "Solicitudes pendientes", solicitudes.filter(estado__in=[EstadoSolicitudRepuesto.APROBADA_POR_ASESOR, EstadoSolicitudRepuesto.EN_REVISION_ALMACEN, EstadoSolicitudRepuesto.PARCIALMENTE_DISPONIBLE]).count(), tone="warning"),
                    self._kpi("compras_confirmadas_mes", "Compras confirmadas del mes", compras.filter(created_at__date__gte=inicio_mes, estado="CONFIRMADA").count()),
                    self._kpi("movimientos_hoy", "Movimientos hoy", movimientos.filter(created_at__date=hoy).count()),
                    self._kpi(
                        "items_solicitud_sin_stock",
                        "Items solicitados sin stock",
                        solicitud_detalles.filter(estado=EstadoSolicitudRepuestoDetalle.SIN_STOCK).count(),
                        tone="danger",
                    ),
                    self._kpi(
                        "unidades_pendientes_entrega",
                        "Unidades pendientes de entrega",
                        sum(
                            max((detalle.cantidad_aprobada or 0) - (detalle.cantidad_entregada or 0), 0)
                            for detalle in solicitud_detalles
                        ),
                        tone="warning",
                    ),
                    self._kpi("compras_borrador", "Compras en borrador", compras.filter(estado=EstadoCompra.BORRADOR).count()),
                ],
                charts=[
                    self._chart(
                        "solicitudes_estado_almacen",
                        "pie",
                        "Estado de solicitudes de repuesto",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in solicitudes.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "solicitudes_detalle_estado_almacen",
                        "bar",
                        "Estado de items solicitados",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in solicitud_detalles.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "top_items_movimiento_almacen",
                        "bar",
                        "Items con mayor movimiento",
                        [
                            {
                                "name": fila["item_inventario__nombre"] or "Item",
                                "value": fila["total"],
                            }
                            for fila in movimientos.values("item_inventario__nombre").annotate(total=Count("id")).order_by("-total")[:6]
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "flujo_almacen_6m",
                        "line",
                        "Compras confirmadas vs movimientos por mes",
                        serie_almacen_flujo,
                        x_key="mes",
                        series=[
                            {"key": "compras", "label": "Compras"},
                            {"key": "movimientos", "label": "Movimientos"},
                        ],
                    ),
                    self._chart(
                        "items_tipo_almacen",
                        "pie",
                        "Distribucion de inventario por tipo",
                        [
                            {"name": fila["tipo_item"], "value": fila["total"]}
                            for fila in items.values("tipo_item").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "compras_estado_almacen",
                        "pie",
                        "Estado de compras",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in compras.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                ],
                tables=[
                    self._table(
                        "items_criticos_almacen",
                        "Stock crítico",
                        ["Código", "Item", "Stock actual", "Stock mínimo"],
                        [
                            {
                                "codigo": item.codigo,
                                "item": item.nombre,
                                "stock_actual": item.stock_actual,
                                "stock_minimo": item.stock_minimo,
                            }
                            for item in items.filter(stock_actual__lte=models.F("stock_minimo")).order_by("stock_actual", "nombre")[:8]
                        ],
                    ),
                    self._table(
                        "solicitudes_pendientes_almacen_tabla",
                        "Solicitudes pendientes de atención",
                        ["Cita", "Estado", "Solicitado por", "Fecha"],
                        [
                            {
                                "cita": str(solicitud.cita_id),
                                "estado": solicitud.estado,
                                "solicitado_por": solicitud.solicitado_por.get_full_name() if solicitud.solicitado_por else "-",
                                "fecha": solicitud.created_at.strftime("%Y-%m-%d %H:%M"),
                            }
                            for solicitud in solicitudes.filter(
                                estado__in=[
                                    EstadoSolicitudRepuesto.APROBADA_POR_ASESOR,
                                    EstadoSolicitudRepuesto.EN_REVISION_ALMACEN,
                                    EstadoSolicitudRepuesto.PARCIALMENTE_DISPONIBLE,
                                ]
                            ).select_related("solicitado_por").order_by("-created_at")[:8]
                        ],
                    ),
                ],
            )
        ]

    def _dashboard_admin(self, empresa, hoy):
        citas = Cita.objects.filter(empresa=empresa)
        pagos = PagoTaller.objects.filter(empresa=empresa).exclude(estado=EstadoPagoTaller.ANULADO)
        items = ItemInventario.objects.filter(empresa=empresa, activo=True)
        usuarios = Usuario.objects.filter(empresa=empresa, is_active=True)
        ordenes = OrdenTrabajoGlobal.objects.filter(empresa=empresa)
        ordenes_detalle = OrdenTrabajoDetalle.objects.filter(empresa=empresa)
        planes_detalle = PlanServicioDetalle.objects.filter(empresa=empresa)
        presupuestos = PresupuestoCita.objects.filter(empresa=empresa)
        solicitudes = SolicitudRepuesto.objects.filter(empresa=empresa)
        solicitud_detalles = SolicitudRepuestoDetalle.objects.filter(empresa=empresa)
        inicio_mes = hoy.replace(day=1)
        serie_finanzas_mensual = self._serie_ultimos_meses(
            {
                "ingresos": {
                    "queryset": pagos.filter(estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO]),
                    "date_field": "recibido_at",
                    "sum_field": "monto_total",
                },
                "compras": {
                    "queryset": Compra.objects.filter(empresa=empresa, estado=EstadoCompra.CONFIRMADA),
                    "date_field": "fecha_compra",
                    "sum_field": "total",
                },
            },
            months=6,
        )
        serie_operacion_mensual = self._serie_ultimos_meses(
            {
                "citas": {
                    "queryset": citas,
                    "date_field": "fecha_hora_inicio_programada",
                },
                "recepciones": {
                    "queryset": RecepcionVehiculo.objects.filter(empresa=empresa),
                    "date_field": "fecha_recepcion",
                },
            },
            months=6,
        )

        return [
            self._section(
                "admin_resumen_general",
                "Resumen general",
                "Vista consolidada del taller, finanzas, usuarios e inventario.",
                kpis=[
                    self._kpi("citas_hoy", "Citas de hoy", citas.filter(fecha_hora_inicio_programada__date=hoy).count()),
                    self._kpi("vehiculos_en_taller", "Vehículos en taller", citas.filter(estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO], vehiculo__isnull=False).values("vehiculo_id").distinct().count()),
                    self._kpi("ingresos_mes", "Ingresos del mes", float(pagos.filter(recibido_at__date__gte=inicio_mes, estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO]).aggregate(total=Sum("monto_total")).get("total") or 0), format_type="currency", tone="success"),
                    self._kpi("presupuestos_pendientes", "Presupuestos pendientes", presupuestos.filter(estado__in=[EstadoPresupuestoCita.COMUNICADO, EstadoPresupuestoCita.AJUSTADO, EstadoPresupuestoCita.APROBADO]).count(), tone="warning"),
                    self._kpi("items_stock_bajo", "Items con stock bajo", items.filter(stock_actual__lte=models.F("stock_minimo")).count(), tone="danger"),
                    self._kpi("usuarios_activos", "Usuarios activos", usuarios.count()),
                    self._kpi("ordenes_abiertas", "Órdenes abiertas", ordenes.filter(estado__in=[EstadoOrdenTrabajoGlobal.ABIERTA, EstadoOrdenTrabajoGlobal.ASIGNADA, EstadoOrdenTrabajoGlobal.EN_PROCESO, EstadoOrdenTrabajoGlobal.PAUSADA]).count()),
                    self._kpi("solicitudes_repuesto_activas", "Solicitudes activas", solicitudes.exclude(estado__in=[EstadoSolicitudRepuesto.ENTREGADA, EstadoSolicitudRepuesto.CERRADA, EstadoSolicitudRepuesto.RECHAZADA_POR_ASESOR]).count(), tone="warning"),
                    self._kpi(
                        "servicios_plan_activos",
                        "Servicios de plan activos",
                        planes_detalle.filter(
                            estado__in=[
                                EstadoPlanServicioDetalle.PENDIENTE,
                                EstadoPlanServicioDetalle.PROGRAMADO,
                                EstadoPlanServicioDetalle.EN_PROCESO,
                                EstadoPlanServicioDetalle.RECOMENDADO,
                            ]
                        ).count(),
                    ),
                    self._kpi(
                        "servicios_urgentes",
                        "Servicios urgentes",
                        planes_detalle.filter(
                            estado__in=[
                                EstadoPlanServicioDetalle.PENDIENTE,
                                EstadoPlanServicioDetalle.PROGRAMADO,
                                EstadoPlanServicioDetalle.EN_PROCESO,
                                EstadoPlanServicioDetalle.RECOMENDADO,
                            ],
                            prioridad__in=["ALTA", "URGENTE"],
                        ).count(),
                        tone="danger",
                    ),
                    self._kpi(
                        "items_repuesto_pendientes_entrega",
                        "Items de repuesto pendientes",
                        solicitud_detalles.exclude(
                            estado__in=[
                                EstadoSolicitudRepuestoDetalle.ENTREGADO,
                                EstadoSolicitudRepuestoDetalle.CANCELADO,
                            ]
                        ).count(),
                        tone="warning",
                    ),
                    self._kpi(
                        "eficiencia_taller_pct",
                        "Eficiencia del taller",
                        round(
                            (
                                float(
                                    ordenes_detalle.filter(
                                        estado=EstadoOrdenTrabajoDetalle.FINALIZADO,
                                        tiempo_real_min__isnull=False,
                                    ).aggregate(total=Sum("tiempo_estandar_min")).get("total")
                                    or 0
                                )
                                /
                                max(
                                    float(
                                        ordenes_detalle.filter(
                                            estado=EstadoOrdenTrabajoDetalle.FINALIZADO,
                                            tiempo_real_min__isnull=False,
                                        ).aggregate(total=Sum("tiempo_real_min")).get("total")
                                        or 0
                                    ),
                                    1.0,
                                )
                            ) * 100,
                            2,
                        ),
                        tone="success",
                    ),
                ],
                charts=[
                    self._chart(
                        "admin_citas_7d",
                        "line",
                        "Citas programadas últimos 7 días",
                        self._serie_ultimos_dias(citas, "fecha_hora_inicio_programada"),
                        x_key="fecha",
                        y_key="total",
                    ),
                    self._chart(
                        "admin_citas_estado",
                        "pie",
                        "Distribución de estados de cita",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in citas.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "admin_plan_estado",
                        "bar",
                        "Estado de servicios del plan",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in planes_detalle.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "admin_ordenes_estado",
                        "pie",
                        "Distribucion de ordenes de trabajo",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in ordenes.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                    ),
                    self._chart(
                        "admin_repuestos_detalle_estado",
                        "bar",
                        "Estado de items de repuesto",
                        [
                            {"name": fila["estado"], "value": fila["total"]}
                            for fila in solicitud_detalles.values("estado").annotate(total=Count("id")).order_by("-total")
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                ],
                tables=[
                    self._table(
                        "admin_vehiculos_taller",
                        "Vehículos actualmente en taller",
                        ["Placa", "Vehículo", "Cliente", "Estado"],
                        [
                            {
                                "placa": cita.vehiculo.placa if cita.vehiculo else "-",
                                "vehiculo": f"{cita.vehiculo.marca} {cita.vehiculo.modelo}" if cita.vehiculo else "Sin vehículo",
                                "cliente": cita.cliente.get_full_name() if cita.cliente else "-",
                                "estado": cita.estado,
                            }
                            for cita in citas.filter(
                                estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO]
                            ).select_related("vehiculo", "cliente").order_by("fecha_hora_inicio_programada")[:8]
                        ],
                    ),
                ],
            ),
            self._section(
                "admin_rendimiento",
                "Rendimiento y demanda",
                "Vehículos, servicios y actividad económica con mayor movimiento.",
                charts=[
                    self._chart(
                        "admin_top_vehiculos",
                        "bar",
                        "Vehículos con más ingresos al taller",
                        [
                            {
                                "name": fila["vehiculo__placa"] or "Sin placa",
                                "value": fila["total"],
                            }
                            for fila in citas.filter(vehiculo__isnull=False)
                            .values("vehiculo__placa")
                            .annotate(total=Count("id"))
                            .order_by("-total")[:6]
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                    self._chart(
                        "admin_ingresos_7d",
                        "line",
                        "Cobros últimos 7 días",
                        self._serie_ultimos_dias(
                            pagos.filter(estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.FACTURADO]),
                            "recibido_at",
                            sum_field="monto_total",
                        ),
                        x_key="fecha",
                        y_key="total",
                    ),
                    self._chart(
                        "admin_finanzas_6m",
                        "bar",
                        "Ingresos vs compras por mes",
                        serie_finanzas_mensual,
                        x_key="mes",
                        series=[
                            {"key": "ingresos", "label": "Ingresos"},
                            {"key": "compras", "label": "Compras"},
                        ],
                    ),
                    self._chart(
                        "admin_operacion_6m",
                        "line",
                        "Citas vs recepciones por mes",
                        serie_operacion_mensual,
                        x_key="mes",
                        series=[
                            {"key": "citas", "label": "Citas"},
                            {"key": "recepciones", "label": "Recepciones"},
                        ],
                    ),
                    self._chart(
                        "admin_top_servicios_plan",
                        "bar",
                        "Servicios mas frecuentes del plan",
                        [
                            {
                                "name": fila["servicio_catalogo__nombre"] or "Servicio",
                                "value": fila["total"],
                            }
                            for fila in planes_detalle.values("servicio_catalogo__nombre").annotate(total=Count("id")).order_by("-total")[:6]
                        ],
                        x_key="name",
                        y_key="value",
                    ),
                ],
                tables=[
                    self._table(
                        "admin_stock_critico",
                        "Items críticos de inventario",
                        ["Código", "Item", "Stock", "Mínimo"],
                        [
                            {
                                "codigo": item.codigo,
                                "item": item.nombre,
                                "stock": item.stock_actual,
                                "minimo": item.stock_minimo,
                            }
                            for item in items.filter(stock_actual__lte=models.F("stock_minimo")).order_by("stock_actual", "nombre")[:8]
                        ],
                    ),
                    self._table(
                        "admin_solicitudes_repuesto",
                        "Solicitudes de repuesto activas",
                        ["Cita", "Estado", "Solicitado por", "Fecha"],
                        [
                            {
                                "cita": str(solicitud.cita_id),
                                "estado": solicitud.estado,
                                "solicitado_por": solicitud.solicitado_por.get_full_name() if solicitud.solicitado_por else "-",
                                "fecha": solicitud.created_at.strftime("%Y-%m-%d %H:%M"),
                            }
                            for solicitud in solicitudes.exclude(
                                estado__in=[
                                    EstadoSolicitudRepuesto.ENTREGADA,
                                    EstadoSolicitudRepuesto.CERRADA,
                                    EstadoSolicitudRepuesto.RECHAZADA_POR_ASESOR,
                                ]
                            ).select_related("solicitado_por").order_by("-created_at")[:8]
                        ],
                    ),
                ],
            ),
        ]

    @action(detail=False, methods=["get"])
    def dashboard_kpis(self, request, **kwargs):
        empresa = request.user.empresa
        rol = self._rol_dashboard(request.user)
        hoy = timezone.localdate()

        sections = []
        if rol == "ADMIN":
            sections.extend(self._dashboard_admin(empresa, hoy))
        elif rol == "USUARIO":
            sections.extend(self._dashboard_usuario(request, empresa, hoy))
        elif rol == "ASESOR DE SERVICIO":
            sections.extend(self._dashboard_asesor(empresa, hoy))
        elif rol in ["MECANICO", "MECÁNICO"]:
            sections.extend(self._dashboard_mecanico(request, empresa, hoy))
        elif rol == "ADMINISTRATIVO":
            sections.extend(self._dashboard_administrativo(empresa, hoy))
        elif rol == "ALMACENERO":
            sections.extend(self._dashboard_almacenero(empresa, hoy))
        else:
            sections.extend(self._dashboard_usuario(request, empresa, hoy))

        resumen = []
        for section in sections:
            resumen.extend(section.get("kpis", [])[:4])

        return response.Response(
            {
                "rol": rol,
                "hoy": hoy.isoformat(),
                "kpis": self._flatten_kpis(sections),
                "summary": resumen[:8],
                "sections": sections,
            }
        )

    @action(detail=False, methods=["get"])
    def usuarios(self, request, **kwargs):
        empresa = request.user.empresa
        rol = self._clean(request.query_params.get("rol"))
        estado = request.query_params.get("estado")
        
        usuarios_qs = Usuario.objects.filter(empresa=empresa)
        if rol:
            usuarios_qs = usuarios_qs.filter(rol__nombre__iexact=rol)
        if estado:
            is_active = estado.lower() == 'activo'
            usuarios_qs = usuarios_qs.filter(is_active=is_active)
            
        total_usuarios = usuarios_qs.count()
        activos = usuarios_qs.filter(is_active=True).count()
        inactivos = total_usuarios - activos
        
        top_clientes = Cita.objects.filter(empresa=empresa, cliente__isnull=False).values("cliente__nombres", "cliente__apellidos", "cliente__email").annotate(total_citas=Count('id')).order_by('-total_citas')[:10]
        
        top_clientes_fmt = [{"nombre": f"{c['cliente__nombres']} {c['cliente__apellidos']}", "email": c['cliente__email'], "citas": c['total_citas']} for c in top_clientes]
        
        return response.Response({
            "kpis": {
                "total_usuarios": total_usuarios,
                "usuarios_activos": activos,
                "usuarios_inactivos": inactivos
            },
            "top_clientes": top_clientes_fmt
        })

    @action(detail=False, methods=["get"])
    def ventas_mostrador(self, request, **kwargs):
        empresa = request.user.empresa
        desde, hasta = self._get_fecha_range(request)
        estado = self._clean(request.query_params.get("estado_venta"))
        
        ventas_qs = VentaMostrador.objects.filter(empresa=empresa, created_at__gte=desde, created_at__lte=hasta)
        if estado:
            ventas_qs = ventas_qs.filter(estado=estado)
            
        total_ventas = ventas_qs.count()
        pagadas = ventas_qs.filter(estado='PAGADA').count()
        pendientes = ventas_qs.filter(estado='PENDIENTE_PAGO').count()
        ingresos_ventas = float(ventas_qs.filter(estado='PAGADA').aggregate(total=Sum("total")).get("total") or 0)
        
        return response.Response({
            "kpis": {
                "total_ventas": total_ventas,
                "ventas_pagadas": pagadas,
                "ventas_pendientes": pendientes,
                "ingresos_ventas_mostrador": ingresos_ventas
            },
            "grafico_ventas": [] 
        })

    @action(detail=False, methods=["get"])
    def compras(self, request, **kwargs):
        empresa = request.user.empresa
        desde, hasta = self._get_fecha_range(request)
        estado = self._clean(request.query_params.get("estado_compra"))
        
        compras_qs = Compra.objects.filter(empresa=empresa, created_at__gte=desde, created_at__lte=hasta)
        if estado:
            compras_qs = compras_qs.filter(estado=estado)
            
        total_compras = compras_qs.count()
        recibidas = compras_qs.filter(estado='RECIBIDA').count()
        pendientes = compras_qs.filter(estado='EN_TRANSITO').count()
        egresos_compras = float(compras_qs.aggregate(total=Sum("total_compra")).get("total") or 0)
        
        return response.Response({
            "kpis": {
                "total_compras": total_compras,
                "compras_recibidas": recibidas,
                "compras_pendientes": pendientes,
                "gastos_compras": egresos_compras
            }
        })

    @action(detail=False, methods=["get"])
    def explorador_datos(self, request, **kwargs):
        import json
        empresa = request.user.empresa
        vista = self._clean(request.query_params.get("vista", ""))
        columnas_str = self._clean(request.query_params.get("columnas", ""))
        filtros_str = request.query_params.get("filtros", "{}")
        
        if not vista or not columnas_str:
            return response.Response({"error": "Faltan parametros vista o columnas"}, status=400)
            
        columnas = [c.strip() for c in columnas_str.split(",") if c.strip()]
        
        try:
            filtros_dict = json.loads(filtros_str)
        except:
            filtros_dict = {}
            
        # Limpiar filtros para asegurarse de que todo es string o lista de strings (seguridad básica)
        safe_filters = {}
        for k, v in filtros_dict.items():
            if isinstance(v, list):
                safe_filters[f"{k}__in"] = [item for item in v if item not in ["", None]]
            elif isinstance(v, (bool, int, float)) or v is None:
                safe_filters[k] = v
            else:
                safe_filters[k] = str(v).strip()
        
        vistas = {
            "vehiculos_citas": lambda: Cita.objects.filter(empresa=empresa).select_related("vehiculo", "cliente", "asesor_responsable"),
            "citas_servicios": lambda: CitaDetalle.objects.filter(empresa=empresa).select_related("cita__vehiculo", "servicio_catalogo"),
            "clientes_ventas": lambda: VentaMostrador.objects.filter(empresa=empresa).select_related("cliente_usuario", "vendido_por"),
            "vehiculos": lambda: Vehiculo.objects.filter(empresa=empresa).select_related("propietario"),
            "citas": lambda: Cita.objects.filter(empresa=empresa).select_related("vehiculo", "cliente", "asesor_responsable"),
            "cita_detalles": lambda: CitaDetalle.objects.filter(empresa=empresa).select_related("cita__vehiculo", "servicio_catalogo"),
            "planes_detalle": lambda: PlanServicioDetalle.objects.filter(empresa=empresa).select_related("plan_servicio__vehiculo", "servicio_catalogo", "recomendado_por"),
            "presupuestos": lambda: PresupuestoCita.objects.filter(empresa=empresa).select_related("cita__vehiculo", "cita__cliente", "comunicado_por"),
            "ordenes_globales": lambda: OrdenTrabajoGlobal.objects.filter(empresa=empresa).select_related("cita__vehiculo", "cita__cliente", "asesor_responsable"),
            "ordenes_detalle": lambda: OrdenTrabajoDetalle.objects.filter(empresa=empresa).select_related("orden_global__cita__vehiculo", "servicio_catalogo", "mecanico_asignado", "plan_detalle"),
            "recepciones": lambda: RecepcionVehiculo.objects.filter(empresa=empresa).select_related("cita__vehiculo", "asesor_registra", "recogido_por"),
            "avances": lambda: AvanceVehiculo.objects.filter(empresa=empresa).select_related("cita__vehiculo", "orden_detalle", "registrado_por"),
            "usuarios": lambda: Usuario.objects.filter(empresa=empresa).select_related("rol"),
            "ventas": lambda: VentaMostrador.objects.filter(empresa=empresa).select_related("cliente_usuario", "vendido_por"),
            "compras": lambda: Compra.objects.filter(empresa=empresa).select_related("proveedor", "registrado_por"),
            "proveedores": lambda: Proveedor.objects.filter(empresa=empresa),
            "pagos_taller": lambda: PagoTaller.objects.filter(empresa=empresa).select_related("cita__vehiculo", "venta", "registrado_por"),
            "items_inventario": lambda: ItemInventario.objects.filter(empresa=empresa).select_related("categoria"),
            "movimientos_inventario": lambda: MovimientoInventario.objects.filter(empresa=empresa).select_related("item_inventario", "registrado_por"),
            "solicitudes_repuesto": lambda: SolicitudRepuesto.objects.filter(empresa=empresa).select_related("cita__vehiculo", "orden_global", "solicitado_por", "aprobado_por_asesor"),
            "solicitudes_repuesto_detalle": lambda: SolicitudRepuestoDetalle.objects.filter(empresa=empresa).select_related("solicitud__cita__vehiculo", "item_inventario", "recibido_taller_por"),
            "vehiculos_en_taller": lambda: Cita.objects.filter(
                empresa=empresa,
                estado__in=[EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO],
            ).select_related("vehiculo", "cliente", "asesor_responsable"),
            "items_stock_bajo": lambda: ItemInventario.objects.filter(
                empresa=empresa,
                stock_actual__lte=models.F("stock_minimo"),
            ).select_related("categoria"),
            "solicitudes_repuesto_activas": lambda: SolicitudRepuesto.objects.filter(empresa=empresa).exclude(
                estado__in=[
                    EstadoSolicitudRepuesto.ENTREGADA,
                    EstadoSolicitudRepuesto.CERRADA,
                    EstadoSolicitudRepuesto.RECHAZADA_POR_ASESOR,
                ]
            ).select_related("cita__vehiculo", "orden_global", "solicitado_por", "aprobado_por_asesor"),
            "solicitudes_detalle_pendientes": lambda: SolicitudRepuestoDetalle.objects.filter(empresa=empresa).exclude(
                estado__in=[
                    EstadoSolicitudRepuestoDetalle.ENTREGADO,
                    EstadoSolicitudRepuestoDetalle.CANCELADO,
                ]
            ).select_related("solicitud__cita__vehiculo", "item_inventario", "recibido_taller_por"),
        }

        qs = vistas[vista]() if vista in vistas else None
        if qs is None and vista == "vehiculos_citas":
            qs = Cita.objects.filter(empresa=empresa).select_related('vehiculo', 'cliente')
        elif qs is None and vista == "citas_servicios":
            # Nota: Necesitamos importar CitaDetalle si no está, asumiendo que podemos usar Cita.detalles
            qs = Cita.objects.filter(empresa=empresa).prefetch_related('detalles__servicio_catalogo')
        elif qs is None and vista == "clientes_ventas":
            qs = VentaMostrador.objects.filter(empresa=empresa).select_related('vendedor')
            # Las ventas rapidas no tienen cliente asociado al usuario normalmente, pero es un ejemplo
        else:
            # Fallbacks a tablas simples
            if qs is not None:
                pass
            elif vista == "vehiculos":
                qs = Vehiculo.objects.filter(empresa=empresa)
            elif vista == "citas":
                qs = Cita.objects.filter(empresa=empresa)
            elif vista == "usuarios":
                qs = Usuario.objects.filter(empresa=empresa)
            elif vista == "ventas":
                qs = VentaMostrador.objects.filter(empresa=empresa)
            elif vista == "compras":
                qs = Compra.objects.filter(empresa=empresa)
            else:
                return response.Response({"error": "Vista no soportada"}, status=400)
            
        try:
            # Aplicar filtros dinámicos
            if safe_filters:
                qs = qs.filter(**safe_filters)
                
            # Ejecutar la consulta dinámica
            resultados = list(qs.values(*columnas)[:1000]) # Limit to 1000 for safety
            return response.Response({"resultados": resultados})
        except Exception as e:
            return response.Response({"error": str(e)}, status=400)
