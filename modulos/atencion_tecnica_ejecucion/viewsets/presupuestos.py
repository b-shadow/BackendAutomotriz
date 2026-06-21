from decimal import Decimal

import stripe
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from urllib.parse import quote
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from modulos.atencion_tecnica_ejecucion.models import (
    PresupuestoCita,
    PresupuestoDetalle,
    EstadoPresupuestoCita,
    EstadoPresupuestoDetalle,
)
from modulos.atencion_tecnica_ejecucion.serializers.presupuestos import (
    PresupuestoCitaSerializer,
)
from modulos.inventario_proveedores_administracion.models import (
    CajaUsuario,
    PagoTaller,
    MovimientoCaja,
    TipoMovimientoCaja,
    TipoOrigenPagoTaller,
    EstadoPagoTaller,
)
from modulos.inventario_proveedores_administracion.services.pagos_qr import (
    LibelulaPaymentClient,
    PagoQRError,
    calcular_monto_cobrado,
    generar_referencia_externa,
    validar_monto_real,
)
from modulos.vehiculos_servicios_plan_citas.models import Cita
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_on_commit,
    AccionAuditoria,
)
from modulos.comunicacion_control_inteligencia.services import notificar_usuarios_on_commit

ESTADOS_PAGO_CONFIRMADOS = [
    EstadoPagoTaller.CONFIRMADO,
    EstadoPagoTaller.RECIBIDO,
    EstadoPagoTaller.FACTURADO,
]


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, 'tenant') or request.user.empresa != request.tenant:
            return False
        return True


class PuedeGestionarPresupuestos(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ['ADMIN', 'ASESOR DE SERVICIO']


class PuedeRegistrarPagos(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ['ADMIN', 'ADMINISTRATIVO']


class PresupuestoCitaViewSet(viewsets.ModelViewSet):
    serializer_class = PresupuestoCitaSerializer
    permission_classes = [IsAuthenticatedTenant]
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ['cita__vehiculo__placa', 'cita__cliente__nombres']
    ordering_fields = ['created_at', 'total', 'estado']
    ordering = ['-created_at']
    filterset_fields = ['estado', 'cita']

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsAuthenticatedTenant()]
        if self.action in ['aprobar', 'rechazar']:
            return [IsAuthenticatedTenant()]
        if self.action in ['simular_pago', 'iniciar_pago_qr', 'iniciar_pago_tarjeta', 'confirmar_pago_tarjeta']:
            return [IsAuthenticatedTenant()]
        if self.action in ['marcar_pagado']:
            return [IsAuthenticatedTenant(), PuedeRegistrarPagos()]
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'comunicar', 'aprobar', 'rechazar', 'ajustar', 'cerrar']:
            return [IsAuthenticatedTenant(), PuedeGestionarPresupuestos()]
        return [IsAuthenticatedTenant()]

    def get_queryset(self):
        qs = PresupuestoCita.objects.filter(empresa=self.request.tenant).select_related(
            'cita', 'cita__vehiculo', 'cita__cliente', 'comunicado_por'
        ).prefetch_related('detalles', 'detalles__servicio_catalogo')

        rol_nombre = self.request.user.rol.nombre if self.request.user.rol else None
        if rol_nombre == 'USUARIO':
            qs = qs.filter(cita__cliente=self.request.user)
        return qs

    def _destinatarios_presupuesto(self, presupuesto):
        return [presupuesto.cita.cliente, presupuesto.cita.asesor_responsable]

    def _notificar_estado_presupuesto(self, presupuesto, request, nuevo_estado, extra=None):
        titulo_map = {
            EstadoPresupuestoCita.BORRADOR: "Presupuesto en borrador",
            EstadoPresupuestoCita.COMUNICADO: "Presupuesto comunicado",
            EstadoPresupuestoCita.APROBADO: "Presupuesto aprobado",
            EstadoPresupuestoCita.RECHAZADO: "Presupuesto rechazado",
            EstadoPresupuestoCita.AJUSTADO: "Presupuesto ajustado",
            EstadoPresupuestoCita.CERRADO: "Presupuesto cerrado",
        }
        mensaje_map = {
            EstadoPresupuestoCita.BORRADOR: f"Se creó un presupuesto para la cita {presupuesto.cita.id}.",
            EstadoPresupuestoCita.COMUNICADO: f"El presupuesto de tu cita por Bs {presupuesto.total} ya está disponible.",
            EstadoPresupuestoCita.APROBADO: "El presupuesto fue aprobado y puede avanzar a ejecución.",
            EstadoPresupuestoCita.RECHAZADO: f"El presupuesto fue rechazado. {(extra or {}).get('motivo_rechazo') or ''}".strip(),
            EstadoPresupuestoCita.AJUSTADO: "El presupuesto fue ajustado y requiere revisión.",
            EstadoPresupuestoCita.CERRADO: "El presupuesto fue cerrado.",
        }
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=self._destinatarios_presupuesto(presupuesto),
            titulo=titulo_map.get(nuevo_estado, "Actualización de presupuesto"),
            mensaje=mensaje_map.get(nuevo_estado, "El presupuesto cambió de estado."),
            tipo=f"presupuesto_{str(nuevo_estado).lower()}",
            entidad_tipo="PresupuestoCita",
            entidad_id=presupuesto.id,
            data={"presupuesto_id": str(presupuesto.id), "estado": nuevo_estado},
            excluir_usuario_ids=[request.user.id],
        )

    def _recalcular_totales(self, presupuesto):
        subtotal = Decimal('0.00')
        for det in presupuesto.detalles.filter(estado=EstadoPresupuestoDetalle.ACTIVO):
            det.subtotal = (Decimal(det.cantidad) * det.precio_unitario).quantize(Decimal('0.01'))
            det.save(update_fields=['subtotal', 'updated_at'])
            subtotal += det.subtotal

        descuento = presupuesto.descuento or Decimal('0.00')
        total = subtotal - descuento
        if total < 0:
            total = Decimal('0.00')

        presupuesto.subtotal = subtotal
        presupuesto.total = total
        presupuesto.save(update_fields=['subtotal', 'total', 'updated_at'])

    def _monto_pagado(self, presupuesto):
        monto = Decimal('0.00')
        for p in PagoTaller.objects.filter(
            empresa=presupuesto.empresa,
            cita=presupuesto.cita,
            estado__in=ESTADOS_PAGO_CONFIRMADOS,
        ):
            monto += p.monto_total or Decimal('0.00')
        return monto

    def _registrar_movimiento_caja_si_aplica(self, request, pago):
        caja = CajaUsuario.objects.filter(
            empresa=request.tenant,
            administrativo=request.user,
            activa=True,
        ).first()
        if not caja:
            return
        MovimientoCaja.objects.create(
            empresa=request.tenant,
            caja=caja,
            tipo=TipoMovimientoCaja.INGRESO,
            concepto=f'Pago presupuesto {pago.id}',
            monto=pago.monto_total,
            pago_taller=pago,
            registrado_por=request.user,
        )

    def _validar_detalle(self, detalle):
        cantidad = int(detalle.get('cantidad', 1))
        precio = Decimal(str(detalle.get('precio_unitario', 0)))
        if cantidad <= 0:
            raise ValueError('La cantidad debe ser mayor que 0.')
        if precio < 0:
            raise ValueError('El precio unitario no puede ser negativo.')

    def _subtotal_desde_detalles_payload(self, detalles):
        subtotal = Decimal('0.00')
        for detalle in detalles:
            self._validar_detalle(detalle)
            cantidad = int(detalle.get('cantidad', 1))
            precio = Decimal(str(detalle.get('precio_unitario', 0)))
            subtotal += (Decimal(cantidad) * precio)
        return subtotal.quantize(Decimal('0.01'))

    def _subtotal_desde_detalles_actuales(self, presupuesto):
        subtotal = Decimal('0.00')
        for det in presupuesto.detalles.filter(estado=EstadoPresupuestoDetalle.ACTIVO):
            subtotal += (Decimal(det.cantidad) * (det.precio_unitario or Decimal('0.00')))
        return subtotal.quantize(Decimal('0.01'))

    def _validar_descuento(self, descuento, subtotal):
        if descuento < Decimal('0.00'):
            raise ValueError('El descuento no puede ser negativo.')
        if descuento > subtotal:
            raise ValueError('El descuento no puede exceder el subtotal.')

    def _crear_detalles_desde_cita(self, presupuesto, cita):
        if not cita.detalles.exists():
            raise ValueError('La cita no tiene servicios programados para presupuestar.')

        for cdet in cita.detalles.all().order_by('orden_visual', 'created_at'):
            nombre = cdet.servicio_catalogo.nombre if cdet.servicio_catalogo else 'Servicio'
            PresupuestoDetalle.objects.create(
                empresa=presupuesto.empresa,
                presupuesto=presupuesto,
                servicio_catalogo=cdet.servicio_catalogo,
                descripcion=nombre,
                cantidad=1,
                tiempo_estandar_min=cdet.tiempo_estandar_min or 0,
                precio_unitario=cdet.precio_referencial or Decimal('0.00'),
                subtotal=Decimal('0.00'),
                estado=EstadoPresupuestoDetalle.ACTIVO,
            )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        cita_id = request.data.get('cita_id')
        if not cita_id:
            return Response({'error': 'cita_id es requerido.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            cita = Cita.objects.get(id=cita_id, empresa=request.tenant)
        except Cita.DoesNotExist:
            return Response({'error': 'Cita no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        if hasattr(cita, 'presupuesto'):
            return Response({'error': 'La cita ya tiene presupuesto asociado.'}, status=status.HTTP_400_BAD_REQUEST)

        descuento = Decimal(str(request.data.get('descuento', 0) or 0))

        presupuesto = PresupuestoCita.objects.create(
            empresa=request.tenant,
            cita=cita,
            estado=EstadoPresupuestoCita.BORRADOR,
            descuento=descuento,
            observaciones=request.data.get('observaciones', ''),
        )

        detalles = request.data.get('detalles', None)
        if detalles:
            subtotal_estimado = self._subtotal_desde_detalles_payload(detalles)
            try:
                self._validar_descuento(descuento, subtotal_estimado)
            except ValueError as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            for detalle in detalles:
                PresupuestoDetalle.objects.create(
                    empresa=request.tenant,
                    presupuesto=presupuesto,
                    servicio_catalogo_id=detalle.get('servicio_catalogo_id'),
                    descripcion=detalle.get('descripcion', 'Ítem manual'),
                    cantidad=int(detalle.get('cantidad', 1)),
                    tiempo_estandar_min=int(detalle.get('tiempo_estandar_min', 0)),
                    precio_unitario=Decimal(str(detalle.get('precio_unitario', 0))),
                    subtotal=Decimal('0.00'),
                    estado=detalle.get('estado', EstadoPresupuestoDetalle.ACTIVO),
                )
        else:
            subtotal_estimado = Decimal('0.00')
            for cdet in cita.detalles.all():
                subtotal_estimado += cdet.precio_referencial or Decimal('0.00')
            subtotal_estimado = subtotal_estimado.quantize(Decimal('0.01'))
            try:
                self._validar_descuento(descuento, subtotal_estimado)
            except ValueError as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            self._crear_detalles_desde_cita(presupuesto, cita)

        self._recalcular_totales(presupuesto)

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='PresupuestoCita',
            entidad_id=str(presupuesto.id),
            descripcion='Presupuesto creado',
            metadata={'cita_id': str(cita.id), 'estado': presupuesto.estado},
        )
        self._notificar_estado_presupuesto(presupuesto, request, EstadoPresupuestoCita.BORRADOR)

        return Response(PresupuestoCitaSerializer(presupuesto).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        presupuesto = self.get_object()
        if presupuesto.estado == EstadoPresupuestoCita.CERRADO:
            return Response({'error': 'No se puede editar un presupuesto CERRADO.'}, status=status.HTTP_400_BAD_REQUEST)

        detalles = request.data.get('detalles', None)
        subtotal_estimado = self._subtotal_desde_detalles_payload(detalles) if detalles is not None else self._subtotal_desde_detalles_actuales(presupuesto)

        descuento = presupuesto.descuento or Decimal('0.00')
        if 'descuento' in request.data:
            descuento = Decimal(str(request.data.get('descuento') or 0))
        try:
            self._validar_descuento(descuento, subtotal_estimado)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        presupuesto.descuento = descuento
        if 'observaciones' in request.data:
            presupuesto.observaciones = request.data.get('observaciones')
        presupuesto.save(update_fields=['descuento', 'observaciones', 'updated_at'])

        if detalles is not None:
            presupuesto.detalles.all().delete()
            for detalle in detalles:
                PresupuestoDetalle.objects.create(
                    empresa=request.tenant,
                    presupuesto=presupuesto,
                    servicio_catalogo_id=detalle.get('servicio_catalogo_id'),
                    descripcion=detalle.get('descripcion', 'Ítem manual'),
                    cantidad=int(detalle.get('cantidad', 1)),
                    tiempo_estandar_min=int(detalle.get('tiempo_estandar_min', 0)),
                    precio_unitario=Decimal(str(detalle.get('precio_unitario', 0))),
                    subtotal=Decimal('0.00'),
                    estado=detalle.get('estado', EstadoPresupuestoDetalle.ACTIVO),
                )

        self._recalcular_totales(presupuesto)
        return Response(PresupuestoCitaSerializer(presupuesto).data)

    def _cambiar_estado(self, presupuesto, nuevo_estado, request, extra=None):
        presupuesto.estado = nuevo_estado
        if nuevo_estado == EstadoPresupuestoCita.COMUNICADO:
            presupuesto.comunicado_por = request.user
            presupuesto.comunicado_at = timezone.now()
        presupuesto.save(update_fields=['estado', 'comunicado_por', 'comunicado_at', 'updated_at'])

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='PresupuestoCita',
            entidad_id=str(presupuesto.id),
            descripcion=f'Presupuesto cambió a {nuevo_estado}',
            metadata=extra or {},
        )
        self._notificar_estado_presupuesto(presupuesto, request, nuevo_estado, extra=extra)

        return Response(PresupuestoCitaSerializer(presupuesto).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def comunicar(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        if presupuesto.estado not in [EstadoPresupuestoCita.BORRADOR, EstadoPresupuestoCita.AJUSTADO]:
            return Response({'error': 'Solo se puede comunicar desde BORRADOR o AJUSTADO.'}, status=status.HTTP_400_BAD_REQUEST)
        return self._cambiar_estado(presupuesto, EstadoPresupuestoCita.COMUNICADO, request)

    @action(detail=True, methods=['post'])
    def aprobar(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        if rol_nombre == 'USUARIO' and presupuesto.cita.cliente_id != request.user.id:
            return Response({'error': 'No autorizado para aprobar este presupuesto.'}, status=status.HTTP_403_FORBIDDEN)
        if presupuesto.estado not in [EstadoPresupuestoCita.COMUNICADO, EstadoPresupuestoCita.AJUSTADO]:
            return Response({'error': 'Solo se puede aprobar desde COMUNICADO o AJUSTADO.'}, status=status.HTTP_400_BAD_REQUEST)
        return self._cambiar_estado(presupuesto, EstadoPresupuestoCita.APROBADO, request)

    @action(detail=True, methods=['post'])
    def rechazar(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        if rol_nombre == 'USUARIO' and presupuesto.cita.cliente_id != request.user.id:
            return Response({'error': 'No autorizado para rechazar este presupuesto.'}, status=status.HTTP_403_FORBIDDEN)
        if presupuesto.estado not in [EstadoPresupuestoCita.COMUNICADO, EstadoPresupuestoCita.AJUSTADO]:
            return Response({'error': 'Solo se puede rechazar desde COMUNICADO o AJUSTADO.'}, status=status.HTTP_400_BAD_REQUEST)
        motivo = request.data.get('motivo', '')
        return self._cambiar_estado(
            presupuesto,
            EstadoPresupuestoCita.RECHAZADO,
            request,
            extra={'motivo_rechazo': motivo},
        )

    @action(detail=True, methods=['post'])
    def ajustar(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        if presupuesto.estado not in [EstadoPresupuestoCita.COMUNICADO, EstadoPresupuestoCita.RECHAZADO]:
            return Response({'error': 'Solo se puede ajustar desde COMUNICADO o RECHAZADO.'}, status=status.HTTP_400_BAD_REQUEST)
        return self._cambiar_estado(presupuesto, EstadoPresupuestoCita.AJUSTADO, request)

    @action(detail=True, methods=['post'])
    def cerrar(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        if presupuesto.estado != EstadoPresupuestoCita.APROBADO:
            return Response({'error': 'Solo se puede cerrar un presupuesto APROBADO.'}, status=status.HTTP_400_BAD_REQUEST)
        return self._cambiar_estado(presupuesto, EstadoPresupuestoCita.CERRADO, request)

    @action(detail=True, methods=['post'], url_path='iniciar-pago-qr')
    @transaction.atomic
    def iniciar_pago_qr(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        if rol_nombre == 'USUARIO' and presupuesto.cita.cliente_id != request.user.id:
            return Response({'error': 'No autorizado para pagar este presupuesto.'}, status=status.HTTP_403_FORBIDDEN)

        total = presupuesto.total or Decimal('0.00')
        pagado_actual = self._monto_pagado(presupuesto)
        pendiente = total - pagado_actual
        if pendiente <= Decimal('0.00'):
            return Response({'error': 'Este presupuesto ya esta pagado al 100%.'}, status=status.HTTP_400_BAD_REQUEST)

        monto_raw = request.data.get('monto')
        if monto_raw in [None, ""]:
            return Response({'error': 'Debe enviar el monto a pagar.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            monto_real = Decimal(str(monto_raw)).quantize(Decimal('0.01'))
        except Exception:
            return Response({'error': 'Monto invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto_real <= Decimal('0.00'):
            return Response({'error': 'Monto de pago invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto_real > pendiente:
            return Response({'error': 'El monto no puede exceder el saldo pendiente.'}, status=status.HTTP_400_BAD_REQUEST)

        fecha_expiracion = parse_datetime(request.data.get('fecha_expiracion') or '')
        if not fecha_expiracion:
            fecha_expiracion = timezone.now() + timedelta(minutes=30)
        if fecha_expiracion <= timezone.now():
            return Response({'error': 'fecha_expiracion debe ser futura.'}, status=status.HTTP_400_BAD_REQUEST)

        ambiente = getattr(settings, 'PAGOS_MODO', 'PRUEBA_REAL').upper()
        try:
            validar_monto_real(monto_real)
            monto_cobrado = calcular_monto_cobrado(monto_real, ambiente)
            if getattr(settings, 'PAGOS_QR_SIMULADO', True):
                monto_cobrado = monto_real
            referencia_externa = generar_referencia_externa(ambiente, 'PRESUPUESTO', str(presupuesto.id))
            codigo_pago = f'PAGO-{timezone.now().strftime("%Y%m%d%H%M%S")}-{str(presupuesto.id)[:6].upper()}'
            pago = PagoTaller.objects.create(
                empresa=request.tenant,
                tipo_origen=TipoOrigenPagoTaller.CITA,
                cita=presupuesto.cita,
                tipo_destino='PRESUPUESTO',
                id_destino=str(presupuesto.id),
                estado=EstadoPagoTaller.PENDIENTE,
                proveedor='LIBELULA_QR',
                ambiente=ambiente,
                codigo_pago=codigo_pago,
                monto_total=monto_real,
                monto_real=monto_real,
                monto_cobrado=monto_cobrado,
                metodo_pago='QR',
                moneda='BOB',
                referencia=referencia_externa,
                referencia_externa=referencia_externa,
                descripcion=request.data.get('descripcion') or f'Pago presupuesto {presupuesto.id}',
                fecha_expiracion=fecha_expiracion,
                registrado_por=request.user,
            )
            if getattr(settings, 'PAGOS_QR_SIMULADO', True):
                token_simulador = timezone.now().strftime('%f') + str(pago.id).replace('-', '')[:16]
                frontend_base = (getattr(settings, 'PAGOS_SIMULADOR_FRONTEND_URL', '') or 'http://localhost:5173').rstrip('/')
                url_simulada = f'{frontend_base}/pagos/simulador/{pago.codigo_pago}/{token_simulador}'
                pago.url_pago = url_simulada
                pago.qr_imagen_url = f'https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={quote(url_simulada)}'
                pago.qr_payload = {'url': url_simulada}
                pago.metadata = {'simulado': True, 'sim_token': token_simulador}
                pago.respuesta_proveedor_raw = {'simulado': True, 'url_pago': url_simulada}
                pago.save(update_fields=['url_pago', 'qr_imagen_url', 'qr_payload', 'metadata', 'respuesta_proveedor_raw', 'updated_at'])
            else:
                libelula = LibelulaPaymentClient()
                callback_url = getattr(settings, 'PAGOS_CALLBACK_URL', '')
                return_url = getattr(settings, 'PAGOS_RETURN_URL', '')
                resp = libelula.crear_cobro(
                    monto_cobrado=monto_cobrado,
                    moneda='BOB',
                    descripcion=pago.descripcion,
                    referencia_externa=referencia_externa,
                    fecha_expiracion=fecha_expiracion,
                    callback_url=callback_url,
                    return_url=return_url,
                )
                pago.id_pago_proveedor = resp.id_pago_proveedor
                pago.id_transaccion_proveedor = resp.id_transaccion_proveedor
                pago.qr_imagen_url = resp.qr_imagen_url
                pago.qr_imagen_base64 = resp.qr_imagen_base64
                pago.url_pago = resp.url_pago
                pago.qr_payload = resp.qr_payload
                pago.respuesta_proveedor_raw = resp.raw
                pago.save(update_fields=[
                    'id_pago_proveedor', 'id_transaccion_proveedor', 'qr_imagen_url', 'qr_imagen_base64',
                    'url_pago', 'qr_payload', 'respuesta_proveedor_raw', 'updated_at'
                ])
            notificar_usuarios_on_commit(
                empresa=request.tenant,
                usuarios=self._destinatarios_presupuesto(presupuesto),
                titulo="Pago QR generado",
                mensaje=f"Se generó un pago QR por Bs {monto_real} para el presupuesto.",
                tipo="presupuesto_pago_qr_generado",
                entidad_tipo="PresupuestoCita",
                entidad_id=presupuesto.id,
                data={"presupuesto_id": str(presupuesto.id), "pago_id": str(pago.id)},
                excluir_usuario_ids=[request.user.id],
            )
            return Response({
                'codigoPago': pago.codigo_pago,
                'pagoId': str(pago.id),
                'estado': pago.estado,
                'proveedor': pago.proveedor,
                'ambiente': pago.ambiente,
                'tipoDestino': pago.tipo_destino,
                'idDestino': pago.id_destino,
                'montoReal': str(pago.monto_real),
                'montoCobrado': str(pago.monto_cobrado),
                'moneda': pago.moneda,
                'descripcion': pago.descripcion,
                'fechaExpiracion': pago.fecha_expiracion.isoformat() if pago.fecha_expiracion else None,
                'qrImagenUrl': pago.qr_imagen_url,
                'qrImagenBase64': pago.qr_imagen_base64,
                'urlPago': pago.url_pago,
                'simulado': bool((pago.metadata or {}).get('simulado')),
            }, status=status.HTTP_201_CREATED)
        except PagoQRError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='simular-pago')
    @transaction.atomic
    def simular_pago(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        if rol_nombre != 'USUARIO':
            return Response({'error': 'Simular pago está disponible solo para cliente.'}, status=status.HTTP_403_FORBIDDEN)
        if rol_nombre == 'USUARIO' and presupuesto.cita.cliente_id != request.user.id:
            return Response({'error': 'No autorizado para pagar este presupuesto.'}, status=status.HTTP_403_FORBIDDEN)

        total = presupuesto.total or Decimal('0.00')
        pagado_actual = self._monto_pagado(presupuesto)
        pendiente = total - pagado_actual
        if pendiente <= Decimal('0.00'):
            return Response({'error': 'Este presupuesto ya esta pagado al 100%.'}, status=status.HTTP_400_BAD_REQUEST)

        monto_raw = request.data.get('monto')
        if monto_raw in [None, ""]:
            return Response({'error': 'Debe enviar el monto a pagar.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            monto = Decimal(str(monto_raw)).quantize(Decimal('0.01'))
        except Exception:
            return Response({'error': 'Monto invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto <= Decimal('0.00'):
            return Response({'error': 'Monto de pago invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto > pendiente:
            return Response({'error': 'El monto no puede exceder el saldo pendiente.'}, status=status.HTTP_400_BAD_REQUEST)
        metodo_pago = (request.data.get('metodo_pago') or 'TARJETA').upper()
        if metodo_pago not in ['TARJETA', 'QR']:
            return Response({'error': 'Metodo de pago invalido para cliente.'}, status=status.HTTP_400_BAD_REQUEST)
        if metodo_pago == 'QR':
            return Response({'error': 'Para QR utiliza el endpoint iniciar-pago-qr.'}, status=status.HTTP_400_BAD_REQUEST)

        pago = PagoTaller.objects.create(
            empresa=request.tenant,
            tipo_origen=TipoOrigenPagoTaller.CITA,
            cita=presupuesto.cita,
            estado=EstadoPagoTaller.CONFIRMADO,
            monto_total=monto,
            monto_real=monto,
            monto_cobrado=monto,
            monto_pagado=monto,
            metodo_pago=metodo_pago,
            moneda='BOB',
            referencia=f'SIM-{timezone.now().strftime("%Y%m%d%H%M%S")}',
            registrado_por=request.user,
            recibido_at=timezone.now(),
            fecha_pago=timezone.now(),
        )
        self._registrar_movimiento_caja_si_aplica(request, pago)

        nuevo_pagado = self._monto_pagado(presupuesto)
        nuevo_pendiente = total - nuevo_pagado
        if nuevo_pendiente <= Decimal('0.00'):
            nuevo_pendiente = Decimal('0.00')
            if presupuesto.estado == EstadoPresupuestoCita.APROBADO:
                presupuesto.estado = EstadoPresupuestoCita.CERRADO
                presupuesto.save(update_fields=['estado', 'updated_at'])

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='PresupuestoCita',
            entidad_id=str(presupuesto.id),
            descripcion='Pago simulado registrado',
            metadata={'monto': str(monto), 'pagado_total': str(nuevo_pagado)},
        )
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=self._destinatarios_presupuesto(presupuesto),
            titulo="Pago registrado",
            mensaje=f"Se registró un pago de Bs {monto} para el presupuesto de la cita.",
            tipo="presupuesto_pago_registrado",
            entidad_tipo="PresupuestoCita",
            entidad_id=presupuesto.id,
            data={"presupuesto_id": str(presupuesto.id), "monto": str(monto)},
            excluir_usuario_ids=[request.user.id],
        )

        return Response(
            {
                'presupuesto': PresupuestoCitaSerializer(presupuesto).data,
                'monto_pagado': str(monto),
                'pagado_total': str(nuevo_pagado),
                'saldo_pendiente': str(nuevo_pendiente),
                'pago_completo': nuevo_pendiente == Decimal('0.00'),
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='marcar-pagado')
    @transaction.atomic
    def marcar_pagado(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        total = presupuesto.total or Decimal('0.00')
        pagado_actual = self._monto_pagado(presupuesto)
        pendiente = total - pagado_actual
        if pendiente <= Decimal('0.00'):
            return Response({'error': 'Este presupuesto ya esta pagado al 100%.'}, status=status.HTTP_400_BAD_REQUEST)

        monto_raw = request.data.get('monto')
        if monto_raw in [None, ""]:
            return Response({'error': 'Debe enviar el monto pagado.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            monto = Decimal(str(monto_raw)).quantize(Decimal('0.01'))
        except Exception:
            return Response({'error': 'Monto invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto <= Decimal('0.00'):
            return Response({'error': 'El monto debe ser mayor que 0.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto > pendiente:
            return Response({'error': 'El monto no puede exceder el saldo pendiente.'}, status=status.HTTP_400_BAD_REQUEST)
        metodo_pago = (request.data.get('metodo_pago') or 'EFECTIVO').upper()
        if metodo_pago != 'EFECTIVO':
            return Response({'error': 'Solo EFECTIVO se registra de forma inmediata. QR/TARJETA siguen su flujo de confirmacion.'}, status=status.HTTP_400_BAD_REQUEST)

        pago = PagoTaller.objects.create(
            empresa=request.tenant,
            tipo_origen=TipoOrigenPagoTaller.CITA,
            cita=presupuesto.cita,
            estado=EstadoPagoTaller.CONFIRMADO,
            monto_total=monto,
            metodo_pago=metodo_pago,
            moneda='BOB',
            referencia=f'{metodo_pago[:4]}-{timezone.now().strftime("%Y%m%d%H%M%S")}',
            registrado_por=request.user,
            recibido_at=timezone.now(),
            fecha_pago=timezone.now(),
            monto_real=monto,
            monto_cobrado=monto,
            monto_pagado=monto,
        )
        self._registrar_movimiento_caja_si_aplica(request, pago)

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='PresupuestoCita',
            entidad_id=str(presupuesto.id),
            descripcion='Presupuesto marcado como pagado en efectivo',
            metadata={'monto': str(monto)},
        )
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=self._destinatarios_presupuesto(presupuesto),
            titulo="Pago en efectivo recibido",
            mensaje=f"Se registró un pago en efectivo de Bs {monto} para el presupuesto.",
            tipo="presupuesto_pago_efectivo",
            entidad_tipo="PresupuestoCita",
            entidad_id=presupuesto.id,
            data={"presupuesto_id": str(presupuesto.id), "monto": str(monto)},
            excluir_usuario_ids=[request.user.id],
        )

        nuevo_pagado = self._monto_pagado(presupuesto)
        nuevo_pendiente = total - nuevo_pagado
        if nuevo_pendiente < Decimal('0.00'):
            nuevo_pendiente = Decimal('0.00')
        if nuevo_pendiente == Decimal('0.00') and presupuesto.estado == EstadoPresupuestoCita.APROBADO:
            presupuesto.estado = EstadoPresupuestoCita.CERRADO
            presupuesto.save(update_fields=['estado', 'updated_at'])
            self._notificar_estado_presupuesto(presupuesto, request, EstadoPresupuestoCita.CERRADO)

        return Response(
            {
                'presupuesto': PresupuestoCitaSerializer(presupuesto).data,
                'monto_pagado': str(monto),
                'pagado_total': str(nuevo_pagado),
                'saldo_pendiente': str(nuevo_pendiente),
                'pago_completo': nuevo_pendiente == Decimal('0.00'),
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='iniciar-pago-tarjeta')
    @transaction.atomic
    def iniciar_pago_tarjeta(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        total = presupuesto.total or Decimal('0.00')
        pagado_actual = self._monto_pagado(presupuesto)
        pendiente = total - pagado_actual
        if pendiente <= Decimal('0.00'):
            return Response({'error': 'Este presupuesto ya esta pagado al 100%.'}, status=status.HTTP_400_BAD_REQUEST)

        monto_raw = request.data.get('monto')
        if monto_raw in [None, ""]:
            return Response({'error': 'Debe enviar el monto a pagar.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            monto_real = Decimal(str(monto_raw)).quantize(Decimal('0.01'))
        except Exception:
            return Response({'error': 'Monto invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto_real <= Decimal('0.00'):
            return Response({'error': 'Monto de pago invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto_real > pendiente:
            return Response({'error': 'El monto no puede exceder el saldo pendiente.'}, status=status.HTTP_400_BAD_REQUEST)

        codigo_pago = f'STR-{timezone.now().strftime("%Y%m%d%H%M%S")}-{str(presupuesto.id)[:6].upper()}'
        pago = PagoTaller.objects.create(
            empresa=request.tenant,
            tipo_origen=TipoOrigenPagoTaller.CITA,
            cita=presupuesto.cita,
            tipo_destino='PRESUPUESTO',
            id_destino=str(presupuesto.id),
            estado=EstadoPagoTaller.PENDIENTE,
            proveedor='STRIPE',
            ambiente='TEST' if settings.STRIPE_MODE == 'test' else 'LIVE',
            codigo_pago=codigo_pago,
            monto_total=monto_real,
            monto_real=monto_real,
            monto_cobrado=monto_real,
            metodo_pago='TARJETA',
            moneda='BOB',
            referencia=f'STRIPE-{codigo_pago}',
            referencia_externa=f'STRIPE-{codigo_pago}',
            descripcion=request.data.get('descripcion') or f'Pago tarjeta presupuesto {presupuesto.id}',
            registrado_por=request.user,
        )

        frontend_base = (request.headers.get('Origin') or getattr(settings, 'PAGOS_RETURN_URL', '') or 'http://localhost:5173').rstrip('/')
        success_url = (
            f"{frontend_base}/{request.tenant.slug}/app"
            f"?stripe_result=success&presupuesto_id={presupuesto.id}&pago_taller_id={pago.id}&session_id={{CHECKOUT_SESSION_ID}}"
        )
        cancel_url = (
            f"{frontend_base}/{request.tenant.slug}/app"
            f"?stripe_result=cancel&presupuesto_id={presupuesto.id}&pago_taller_id={pago.id}"
        )

        try:
            currency = (getattr(settings, 'STRIPE_CURRENCY', 'usd') or 'usd').lower()
            session = stripe.checkout.Session.create(
                mode='payment',
                payment_method_types=['card'],
                line_items=[
                    {
                        'price_data': {
                            'currency': currency,
                            'product_data': {'name': pago.descripcion},
                            'unit_amount': int((monto_real * Decimal('100')).quantize(Decimal('1'))),
                        },
                        'quantity': 1,
                    }
                ],
                metadata={
                    'pago_taller_id': str(pago.id),
                    'presupuesto_id': str(presupuesto.id),
                    'tenant_slug': request.tenant.slug,
                },
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except Exception as exc:
            pago.estado = EstadoPagoTaller.ERROR
            pago.metadata = {'stripe_error': str(exc)}
            pago.save(update_fields=['estado', 'metadata', 'updated_at'])
            return Response({'error': f'No se pudo iniciar pago con Stripe: {exc}'}, status=status.HTTP_400_BAD_REQUEST)

        pago.id_pago_proveedor = session.id
        pago.url_pago = session.url
        pago.respuesta_proveedor_raw = {'checkout_session_id': session.id}
        pago.save(update_fields=['id_pago_proveedor', 'url_pago', 'respuesta_proveedor_raw', 'updated_at'])
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=self._destinatarios_presupuesto(presupuesto),
            titulo="Pago con tarjeta iniciado",
            mensaje=f"Se inició un pago con tarjeta por Bs {monto_real} para el presupuesto.",
            tipo="presupuesto_pago_tarjeta_iniciado",
            entidad_tipo="PresupuestoCita",
            entidad_id=presupuesto.id,
            data={"presupuesto_id": str(presupuesto.id), "pago_id": str(pago.id)},
            excluir_usuario_ids=[request.user.id],
        )

        return Response(
            {
                'pagoId': str(pago.id),
                'checkoutUrl': session.url,
                'sessionId': session.id,
                'estado': pago.estado,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='confirmar-pago-tarjeta')
    @transaction.atomic
    def confirmar_pago_tarjeta(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        pago_taller_id = request.data.get('pago_taller_id')
        session_id = request.data.get('session_id')
        if not pago_taller_id or not session_id:
            return Response({'error': 'pago_taller_id y session_id son requeridos.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            pago = PagoTaller.objects.get(
                id=pago_taller_id,
                empresa=request.tenant,
                cita=presupuesto.cita,
                tipo_destino='PRESUPUESTO',
                id_destino=str(presupuesto.id),
                metodo_pago='TARJETA',
            )
        except PagoTaller.DoesNotExist:
            return Response({'error': 'Pago de tarjeta no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        if pago.estado == EstadoPagoTaller.CONFIRMADO:
            return Response({'ok': True, 'estado': pago.estado}, status=status.HTTP_200_OK)
        if pago.estado in [EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO, EstadoPagoTaller.ANULADO]:
            return Response({'error': f'El pago no puede confirmarse en estado {pago.estado}.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except Exception as exc:
            return Response({'error': f'No se pudo consultar Stripe: {exc}'}, status=status.HTTP_400_BAD_REQUEST)

        if session.id != pago.id_pago_proveedor:
            return Response({'error': 'La sesion de Stripe no coincide con el pago.'}, status=status.HTTP_400_BAD_REQUEST)
        if session.payment_status != 'paid':
            return Response({'error': f'El pago no esta confirmado en Stripe. Estado: {session.payment_status}'}, status=status.HTTP_400_BAD_REQUEST)

        pago.estado = EstadoPagoTaller.CONFIRMADO
        pago.monto_pagado = pago.monto_total
        pago.fecha_pago = timezone.now()
        pago.recibido_at = pago.fecha_pago
        pago.save(update_fields=['estado', 'monto_pagado', 'fecha_pago', 'recibido_at', 'updated_at'])
        self._registrar_movimiento_caja_si_aplica(request, pago)

        nuevo_pagado = self._monto_pagado(presupuesto)
        nuevo_pendiente = (presupuesto.total or Decimal('0.00')) - nuevo_pagado
        if nuevo_pendiente < Decimal('0.00'):
            nuevo_pendiente = Decimal('0.00')
        if nuevo_pendiente == Decimal('0.00') and presupuesto.estado == EstadoPresupuestoCita.APROBADO:
            presupuesto.estado = EstadoPresupuestoCita.CERRADO
            presupuesto.save(update_fields=['estado', 'updated_at'])
            self._notificar_estado_presupuesto(presupuesto, request, EstadoPresupuestoCita.CERRADO)

        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=self._destinatarios_presupuesto(presupuesto),
            titulo="Pago con tarjeta confirmado",
            mensaje=f"Se confirmó el pago con tarjeta del presupuesto por Bs {pago.monto_total}.",
            tipo="presupuesto_pago_tarjeta_confirmado",
            entidad_tipo="PresupuestoCita",
            entidad_id=presupuesto.id,
            data={"presupuesto_id": str(presupuesto.id), "pago_id": str(pago.id)},
            excluir_usuario_ids=[request.user.id],
        )

        return Response(
            {
                'ok': True,
                'estado': pago.estado,
                'pagado_total': str(nuevo_pagado),
                'saldo_pendiente': str(nuevo_pendiente),
            },
            status=status.HTTP_200_OK,
        )



