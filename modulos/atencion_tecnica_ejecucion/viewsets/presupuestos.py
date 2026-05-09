from decimal import Decimal

from django.db import transaction
from django.utils import timezone
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
    PagoTaller,
    TipoOrigenPagoTaller,
    EstadoPagoTaller,
)
from modulos.vehiculos_servicios_plan_citas.models import Cita
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_on_commit,
    AccionAuditoria,
)


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
        if self.action in ['simular_pago']:
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
        ).exclude(estado=EstadoPagoTaller.ANULADO):
            monto += p.monto_total or Decimal('0.00')
        return monto

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

    @action(detail=True, methods=['post'], url_path='simular-pago')
    @transaction.atomic
    def simular_pago(self, request, pk=None, **kwargs):
        presupuesto = self.get_object()
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        if rol_nombre != 'USUARIO':
            return Response({'error': 'Simular pago está disponible solo para cliente.'}, status=status.HTTP_403_FORBIDDEN)
        if rol_nombre == 'USUARIO' and presupuesto.cita.cliente_id != request.user.id:
            return Response({'error': 'No autorizado para pagar este presupuesto.'}, status=status.HTTP_403_FORBIDDEN)

        porcentaje = Decimal(str(request.data.get('porcentaje') or '0'))
        if porcentaje not in [Decimal('25'), Decimal('50'), Decimal('75'), Decimal('100')]:
            return Response({'error': 'El porcentaje debe ser 25, 50, 75 o 100.'}, status=status.HTTP_400_BAD_REQUEST)

        total = presupuesto.total or Decimal('0.00')
        pagado_actual = self._monto_pagado(presupuesto)
        pendiente = total - pagado_actual
        if pendiente <= Decimal('0.00'):
            return Response({'error': 'Este presupuesto ya esta pagado al 100%.'}, status=status.HTTP_400_BAD_REQUEST)

        monto = (pendiente * (porcentaje / Decimal('100'))).quantize(Decimal('0.01'))
        if monto <= Decimal('0.00'):
            return Response({'error': 'Monto de pago invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if monto > pendiente:
            monto = pendiente

        PagoTaller.objects.create(
            empresa=request.tenant,
            tipo_origen=TipoOrigenPagoTaller.CITA,
            cita=presupuesto.cita,
            estado=EstadoPagoTaller.RECIBIDO,
            monto_total=monto,
            metodo_pago='SIMULADO',
            moneda='BOB',
            referencia=f'SIM-{timezone.now().strftime("%Y%m%d%H%M%S")}',
            registrado_por=request.user,
            recibido_at=timezone.now(),
        )

        nuevo_pagado = self._monto_pagado(presupuesto)
        nuevo_pendiente = total - nuevo_pagado
        if nuevo_pendiente <= Decimal('0.00'):
            nuevo_pendiente = Decimal('0.00')

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='PresupuestoCita',
            entidad_id=str(presupuesto.id),
            descripcion='Pago simulado registrado',
            metadata={'porcentaje': str(porcentaje), 'monto': str(monto), 'pagado_total': str(nuevo_pagado)},
        )

        return Response(
            {
                'presupuesto': PresupuestoCitaSerializer(presupuesto).data,
                'monto_pagado': str(monto),
                'pagado_total': str(nuevo_pagado),
                'saldo_pendiente': str(nuevo_pendiente),
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

        PagoTaller.objects.create(
            empresa=request.tenant,
            tipo_origen=TipoOrigenPagoTaller.CITA,
            cita=presupuesto.cita,
            estado=EstadoPagoTaller.RECIBIDO,
            monto_total=monto,
            metodo_pago='EFECTIVO',
            moneda='BOB',
            referencia=f'EFEC-{timezone.now().strftime("%Y%m%d%H%M%S")}',
            registrado_por=request.user,
            recibido_at=timezone.now(),
        )

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='PresupuestoCita',
            entidad_id=str(presupuesto.id),
            descripcion='Presupuesto marcado como pagado en efectivo',
            metadata={'monto': str(monto)},
        )

        nuevo_pagado = self._monto_pagado(presupuesto)
        nuevo_pendiente = total - nuevo_pagado
        if nuevo_pendiente < Decimal('0.00'):
            nuevo_pendiente = Decimal('0.00')

        return Response(
            {
                'presupuesto': PresupuestoCitaSerializer(presupuesto).data,
                'monto_pagado': str(monto),
                'pagado_total': str(nuevo_pagado),
                'saldo_pendiente': str(nuevo_pendiente),
            },
            status=status.HTTP_200_OK
        )

