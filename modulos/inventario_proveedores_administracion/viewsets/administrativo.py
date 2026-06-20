from decimal import Decimal
import uuid
from urllib.parse import quote
from io import BytesIO
from pathlib import Path

import stripe
import csv
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.conf import settings
from django.http import HttpResponse
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from modulos.inventario_proveedores_administracion.models import (
    CajaUsuario,
    Compra,
    CompraDetalle,
    EstadoCompra,
    EstadoPagoTaller,
    EstadoVentaMostrador,
    Factura,
    ItemInventario,
    MovimientoCaja,
    MovimientoInventario,
    PagoTaller,
    Proveedor,
    TipoMovimientoCaja,
    TipoMovimientoInventario,
    TipoOrigenPagoTaller,
    VentaMostrador,
    VentaMostradorDetalle,
)
from modulos.inventario_proveedores_administracion.serializers.ventas_pagos import (
    CajaUsuarioSerializer,
    FacturaSerializer,
    MovimientoCajaSerializer,
    PagoTallerSerializer,
    VentaMostradorSerializer,
)
from modulos.inventario_proveedores_administracion.serializers.inventario import ProveedorSerializer
from modulos.inventario_proveedores_administracion.services.pagos_qr import (
    LibelulaPaymentClient,
    PagoQRError,
    calcular_monto_cobrado,
    estado_desde_proveedor,
    generar_referencia_externa,
    hash_callback,
    monto_esperado_para_validacion,
    validar_monto_real,
)
from modulos.comunicacion_control_inteligencia.services import notificar_usuarios_on_commit


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and hasattr(request, "tenant")
            and request.user.empresa == request.tenant
        )


class PuedeGestionAdministrativa(permissions.BasePermission):
    def has_permission(self, request, view):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        return rol in ["ADMIN", "ADMINISTRATIVO", "ALMACENERO", "ASESOR DE SERVICIO"]


class PuedeGestionarCajaPagos(permissions.BasePermission):
    def has_permission(self, request, view):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        return rol in ["ADMIN", "ADMINISTRATIVO"]


def destinatarios_pago_o_venta(obj):
    if isinstance(obj, PagoTaller):
        if obj.cita:
            return [obj.cita.cliente, obj.cita.asesor_responsable]
        if obj.venta:
            return [obj.venta.cliente_usuario, obj.venta.vendido_por]
        return [obj.registrado_por]
    if isinstance(obj, VentaMostrador):
        return [obj.cliente_usuario, obj.vendido_por]
    if isinstance(obj, Compra):
        return [obj.registrado_por]
    if isinstance(obj, Factura):
        return destinatarios_pago_o_venta(obj.pago_taller)
    return []


def notificar_estado_pago(obj, titulo, mensaje, tipo, *, estado=None, excluir_usuario_ids=None):
    if not getattr(obj, "empresa", None):
        return
    entidad_tipo = obj.__class__.__name__
    data = {}
    if estado:
        data["estado"] = str(estado)
    if isinstance(obj, PagoTaller):
        data["pago_id"] = str(obj.id)
    if isinstance(obj, VentaMostrador):
        data["venta_id"] = str(obj.id)
    if isinstance(obj, Compra):
        data["compra_id"] = str(obj.id)
    if isinstance(obj, Factura):
        data["factura_id"] = str(obj.id)
    notificar_usuarios_on_commit(
        empresa=obj.empresa,
        usuarios=destinatarios_pago_o_venta(obj),
        titulo=titulo,
        mensaje=mensaje,
        tipo=tipo,
        entidad_tipo=entidad_tipo,
        entidad_id=obj.id,
        data=data,
        excluir_usuario_ids=excluir_usuario_ids or [],
    )


def procesar_callback_libelula(payload: dict, headers, tenant=None):
    try:
        cliente = LibelulaPaymentClient()
        if not cliente.validar_callback(headers):
            return {"ok": False, "status": status.HTTP_401_UNAUTHORIZED, "body": {"error": "callback no autorizado"}}
    except PagoQRError:
        return {"ok": False, "status": status.HTTP_500_INTERNAL_SERVER_ERROR, "body": {"error": "configuracion libelula invalida"}}

    referencia_externa = payload.get("reference") or payload.get("referenciaExterna")
    id_pago_proveedor = payload.get("payment_id") or payload.get("idPagoProveedor") or payload.get("id")
    estado_proveedor = payload.get("status") or payload.get("estado")
    monto_pagado = payload.get("paid_amount") or payload.get("montoPagado") or payload.get("amount")
    moneda = payload.get("currency") or payload.get("moneda") or "BOB"
    id_tx = payload.get("transaction_id") or payload.get("idTransaccionProveedor")

    qs = PagoTaller.objects.all()
    if tenant is not None:
        qs = qs.filter(empresa=tenant)
    pago = qs.filter(Q(referencia_externa=referencia_externa) | Q(id_pago_proveedor=id_pago_proveedor)).order_by("-created_at").first()
    if not pago:
        return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "detail": "pago no encontrado"}}

    callback_hash = hash_callback(payload)
    if pago.callback_ultimo_hash and pago.callback_ultimo_hash == callback_hash:
        return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "detail": "callback duplicado"}}

    pago.callback_ultimo_hash = callback_hash
    pago.callback_intentos = (pago.callback_intentos or 0) + 1
    pago.respuesta_proveedor_raw = payload
    pago.id_transaccion_proveedor = id_tx or pago.id_transaccion_proveedor
    pago.save(update_fields=["callback_ultimo_hash", "callback_intentos", "respuesta_proveedor_raw", "id_transaccion_proveedor", "updated_at"])

    estado_norm = estado_desde_proveedor(estado_proveedor)
    if estado_norm == EstadoPagoTaller.CONFIRMADO:
        ahora = timezone.now()
        if pago.estado == EstadoPagoTaller.CONFIRMADO:
            return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado, "detalle": "ya_confirmado"}}
        if pago.estado in [EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO]:
            return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado, "detalle": "estado_final"}}
        if pago.fecha_expiracion and ahora > pago.fecha_expiracion:
            pago.estado = EstadoPagoTaller.VENCIDO
            pago.save(update_fields=["estado", "updated_at"])
            return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado, "detalle": "vencido"}}
        if (moneda or "").upper() != "BOB":
            pago.estado = EstadoPagoTaller.RECHAZADO
            pago.save(update_fields=["estado", "updated_at"])
            return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado, "detalle": "moneda_invalida"}}
        esperado = monto_esperado_para_validacion(pago)
        monto_pagado_dec = Decimal(str(monto_pagado or "0")).quantize(Decimal("0.01"))
        if monto_pagado_dec != esperado:
            pago.estado = EstadoPagoTaller.MONTO_INCORRECTO
            pago.monto_pagado = monto_pagado_dec
            pago.save(update_fields=["estado", "monto_pagado", "updated_at"])
            return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado, "detalle": "monto_incorrecto"}}
        pago.estado = EstadoPagoTaller.CONFIRMADO
        pago.monto_pagado = monto_pagado_dec
        pago.fecha_pago = ahora
        pago.recibido_at = ahora
        pago.save(update_fields=["estado", "monto_pagado", "fecha_pago", "recibido_at", "updated_at"])
        notificar_estado_pago(
            pago,
            "Pago QR confirmado",
            f"Se confirmó el pago {pago.codigo_pago or pago.id} por Bs {pago.monto_total}.",
            "pago_qr_confirmado_callback",
            estado=pago.estado,
        )
        return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado}}

    if estado_norm in [EstadoPagoTaller.FALLIDO, EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO, EstadoPagoTaller.PROCESANDO]:
        pago.estado = estado_norm
        pago.save(update_fields=["estado", "updated_at"])
        notificar_estado_pago(
            pago,
            "Pago QR actualizado",
            f"El pago {pago.codigo_pago or pago.id} cambió a estado {pago.estado}.",
            "pago_qr_estado_actualizado_callback",
            estado=pago.estado,
        )
    return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado}}


class ProveedorViewSet(viewsets.ModelViewSet):
    serializer_class = ProveedorSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionAdministrativa]

    def get_queryset(self):
        qs = Proveedor.objects.filter(empresa=self.request.tenant).order_by("nombre")
        activo = self.request.query_params.get("activo")
        search = (self.request.query_params.get("search") or "").strip()
        if activo in ["true", "false"]:
            qs = qs.filter(activo=(activo == "true"))
        if search:
            qs = qs.filter(
                Q(nombre__icontains=search)
                | Q(contacto__icontains=search)
                | Q(email__icontains=search)
                | Q(telefono__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        serializer.save(empresa=self.request.tenant)


class CompraViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticatedTenant, PuedeGestionAdministrativa]

    def get_queryset(self):
        return Compra.objects.filter(empresa=self.request.tenant).prefetch_related("detalles").order_by("-created_at")

    def get_object(self):
        pk = self.kwargs.get("pk")
        return self.get_queryset().get(pk=pk)

    def _serialize(self, compra):
        return {
            "id": str(compra.id),
            "proveedor_id": str(compra.proveedor_id) if compra.proveedor_id else None,
            "proveedor_nombre": compra.proveedor.nombre if compra.proveedor else None,
            "numero_documento": compra.numero_documento,
            "estado": compra.estado,
            "fecha_compra": compra.fecha_compra.isoformat() if compra.fecha_compra else None,
            "subtotal": float(compra.subtotal or 0),
            "total": float(compra.total or 0),
            "detalles": [
                {
                    "id": str(d.id),
                    "item_inventario_id": str(d.item_inventario_id) if d.item_inventario_id else None,
                    "item_nombre": d.item_inventario.nombre if d.item_inventario else None,
                    "cantidad": d.cantidad,
                    "costo_unitario": float(d.costo_unitario or 0),
                    "subtotal": float(d.subtotal or 0),
                }
                for d in compra.detalles.all()
            ],
            "created_at": compra.created_at.isoformat(),
        }

    def _obtener_o_crear_caja_activa(self, request):
        caja = CajaUsuario.objects.filter(
            empresa=request.tenant,
            administrativo=request.user,
            activa=True,
        ).first()
        if caja:
            return caja
        return CajaUsuario.objects.create(
            empresa=request.tenant,
            administrativo=request.user,
            nombre=f"Caja {request.user.nombres}",
            activa=True,
        )

    def list(self, request, *args, **kwargs):
        data = [self._serialize(c) for c in self.get_queryset()]
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        return Response(self._serialize(self.get_object()))

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        payload = request.data
        proveedor_id = payload.get("proveedor_id")
        detalles = payload.get("detalles", [])
        if not detalles:
            return Response({"error": "Debe enviar al menos un detalle."}, status=status.HTTP_400_BAD_REQUEST)

        proveedor = None
        if proveedor_id:
            try:
                proveedor = Proveedor.objects.get(id=proveedor_id, empresa=request.tenant, activo=True)
            except Proveedor.DoesNotExist:
                return Response({"error": "Proveedor no valido o inactivo."}, status=status.HTTP_400_BAD_REQUEST)

        compra = Compra.objects.create(
            empresa=request.tenant,
            proveedor=proveedor,
            numero_documento=payload.get("numero_documento") or f"CMP-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            estado=payload.get("estado") or EstadoCompra.BORRADOR,
            fecha_compra=payload.get("fecha_compra") or timezone.now().date(),
            registrado_por=request.user,
            observaciones=payload.get("observaciones", ""),
            subtotal=Decimal("0.00"),
            total=Decimal("0.00"),
        )

        subtotal = Decimal("0.00")
        for d in detalles:
            item_id = d.get("item_inventario_id")
            cantidad = int(d.get("cantidad") or 0)
            costo = Decimal(str(d.get("costo_unitario") or 0))
            if cantidad <= 0 or costo < 0:
                return Response({"error": "Cantidad/costo invalido."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                item = ItemInventario.objects.get(id=item_id, empresa=request.tenant)
            except ItemInventario.DoesNotExist:
                return Response({"error": "Item de inventario invalido."}, status=status.HTTP_400_BAD_REQUEST)
            sub = (Decimal(cantidad) * costo).quantize(Decimal("0.01"))
            subtotal += sub
            CompraDetalle.objects.create(
                empresa=request.tenant,
                compra=compra,
                item_inventario=item,
                cantidad=cantidad,
                costo_unitario=costo,
                subtotal=sub,
            )

        compra.subtotal = subtotal
        compra.total = subtotal
        compra.save(update_fields=["subtotal", "total", "updated_at"])
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=destinatarios_pago_o_venta(compra),
            titulo="Compra registrada",
            mensaje=f"Se registró la compra {compra.numero_documento} por Bs {compra.total}.",
            tipo="compra_registrada",
            entidad_tipo="Compra",
            entidad_id=compra.id,
            data={"compra_id": str(compra.id), "estado": compra.estado},
            excluir_usuario_ids=[request.user.id],
        )
        return Response(self._serialize(compra), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="marcar-recibida")
    @transaction.atomic
    def marcar_recibida(self, request, pk=None, **kwargs):
        compra = self.get_object()
        if compra.estado == EstadoCompra.CONFIRMADA:
            return Response({"error": "La compra ya fue recibida."}, status=status.HTTP_400_BAD_REQUEST)
        if compra.estado == EstadoCompra.ANULADA:
            return Response({"error": "No se puede recibir una compra anulada."}, status=status.HTTP_400_BAD_REQUEST)

        for det in compra.detalles.select_related("item_inventario"):
            item = det.item_inventario
            if not item:
                continue
            stock_anterior = item.stock_actual
            item.stock_actual = stock_anterior + det.cantidad
            item.save(update_fields=["stock_actual", "updated_at"])
            MovimientoInventario.objects.create(
                empresa=request.tenant,
                item_inventario=item,
                tipo_movimiento=TipoMovimientoInventario.ENTRADA_COMPRA,
                cantidad=det.cantidad,
                stock_anterior=stock_anterior,
                stock_posterior=item.stock_actual,
                referencia_tipo="Compra",
                referencia_id=compra.id,
                registrado_por=request.user,
                observacion=f"Recepcion compra {compra.numero_documento}",
            )

        compra.estado = EstadoCompra.CONFIRMADA
        compra.save(update_fields=["estado", "updated_at"])

        caja = self._obtener_o_crear_caja_activa(request)
        proveedor = compra.proveedor.nombre if compra.proveedor else "Proveedor"
        concepto_compra = (compra.observaciones or "").strip()
        if not concepto_compra:
            numero = compra.numero_documento or str(compra.id)
            concepto_compra = f"Compra insumos {numero} - {proveedor}"
        MovimientoCaja.objects.create(
            empresa=request.tenant,
            caja=caja,
            tipo=TipoMovimientoCaja.EGRESO,
            concepto=concepto_compra,
            monto=compra.total,
            registrado_por=request.user,
        )
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=destinatarios_pago_o_venta(compra),
            titulo="Compra recibida",
            mensaje=f"La compra {compra.numero_documento} fue recibida e ingresó a inventario.",
            tipo="compra_recibida",
            entidad_tipo="Compra",
            entidad_id=compra.id,
            data={"compra_id": str(compra.id), "estado": compra.estado},
            excluir_usuario_ids=[request.user.id],
        )
        return Response(self._serialize(compra))


class VentaMostradorViewSet(viewsets.ModelViewSet):
    serializer_class = VentaMostradorSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionAdministrativa]

    def get_queryset(self):
        return VentaMostrador.objects.filter(empresa=self.request.tenant).prefetch_related("detalles").order_by("-created_at")

    def _obtener_o_crear_caja_activa(self, request):
        caja = CajaUsuario.objects.filter(
            empresa=request.tenant,
            administrativo=request.user,
            activa=True,
        ).first()
        if caja:
            return caja
        return CajaUsuario.objects.create(
            empresa=request.tenant,
            administrativo=request.user,
            nombre=f"Caja {request.user.nombres}",
            activa=True,
        )

    def _registrar_movimiento_caja_si_aplica(self, request, pago):
        caja = self._obtener_o_crear_caja_activa(request)
        cliente = "Cliente"
        if pago.venta:
            if pago.venta.cliente_usuario:
                cliente = f"{pago.venta.cliente_usuario.nombres} {pago.venta.cliente_usuario.apellidos or ''}".strip() or "Cliente"
            else:
                cliente = pago.venta.cliente_nombre_libre or "Cliente"
        MovimientoCaja.objects.create(
            empresa=request.tenant,
            caja=caja,
            tipo=TipoMovimientoCaja.INGRESO,
            concepto=f"Ingreso venta mostrador - {cliente}",
            monto=pago.monto_total,
            pago_taller=pago,
            venta=pago.venta,
            registrado_por=request.user,
        )

    def _confirmar_venta_stock(self, request, venta):
        if venta.estado == EstadoVentaMostrador.CONFIRMADA:
            return
        if venta.estado == EstadoVentaMostrador.ANULADA:
            raise ValueError("La venta esta anulada.")

        for det in venta.detalles.select_related("item_inventario"):
            item = det.item_inventario
            if not item:
                continue
            if item.stock_actual < det.cantidad:
                raise ValueError(f"Stock insuficiente para {item.nombre}.")
            stock_anterior = item.stock_actual
            item.stock_actual = stock_anterior - det.cantidad
            item.save(update_fields=["stock_actual", "updated_at"])
            MovimientoInventario.objects.create(
                empresa=request.tenant,
                item_inventario=item,
                tipo_movimiento=TipoMovimientoInventario.SALIDA_VENTA,
                cantidad=-det.cantidad,
                stock_anterior=stock_anterior,
                stock_posterior=item.stock_actual,
                referencia_tipo="VentaMostrador",
                referencia_id=venta.id,
                registrado_por=request.user,
                observacion=f"Confirmacion venta {venta.id}",
            )

        venta.estado = EstadoVentaMostrador.CONFIRMADA
        venta.save(update_fields=["estado", "updated_at"])

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        payload = request.data
        detalles = payload.get("detalles", [])
        if not detalles:
            return Response({"error": "Debe enviar detalles de venta."}, status=status.HTTP_400_BAD_REQUEST)

        venta = VentaMostrador.objects.create(
            empresa=request.tenant,
            cliente_usuario_id=payload.get("cliente_usuario_id"),
            cliente_nombre_libre=payload.get("cliente_nombre_libre"),
            cliente_documento=payload.get("cliente_documento"),
            vendido_por=request.user,
            estado=payload.get("estado") or EstadoVentaMostrador.BORRADOR,
            subtotal=Decimal("0.00"),
            total=Decimal("0.00"),
        )

        subtotal = Decimal("0.00")
        for d in detalles:
            item_id = d.get("item_inventario_id")
            cantidad = int(d.get("cantidad") or 0)
            precio = Decimal(str(d.get("precio_unitario") or 0))
            if cantidad <= 0 or precio < 0:
                return Response({"error": "Cantidad/precio invalido."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                item = ItemInventario.objects.get(id=item_id, empresa=request.tenant, activo=True)
            except ItemInventario.DoesNotExist:
                return Response({"error": "Item no valido para venta."}, status=status.HTTP_400_BAD_REQUEST)
            if item.stock_actual < cantidad:
                return Response({"error": f"Stock insuficiente para {item.nombre}."}, status=status.HTTP_400_BAD_REQUEST)
            sub = (Decimal(cantidad) * precio).quantize(Decimal("0.01"))
            subtotal += sub
            VentaMostradorDetalle.objects.create(
                empresa=request.tenant,
                venta=venta,
                item_inventario=item,
                cantidad=cantidad,
                precio_unitario=precio,
                subtotal=sub,
            )

        venta.subtotal = subtotal
        venta.total = subtotal
        venta.save(update_fields=["subtotal", "total", "updated_at"])
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=destinatarios_pago_o_venta(venta),
            titulo="Venta de mostrador creada",
            mensaje=f"Se registró una venta de mostrador por Bs {venta.total}.",
            tipo="venta_mostrador_creada",
            entidad_tipo="VentaMostrador",
            entidad_id=venta.id,
            data={"venta_id": str(venta.id), "estado": venta.estado},
            excluir_usuario_ids=[request.user.id],
        )
        return Response(VentaMostradorSerializer(venta).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="confirmar")
    @transaction.atomic
    def confirmar(self, request, pk=None, **kwargs):
        venta = self.get_object()
        if venta.estado == EstadoVentaMostrador.CONFIRMADA:
            return Response({"error": "La venta ya esta confirmada."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            self._confirmar_venta_stock(request, venta)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=destinatarios_pago_o_venta(venta),
            titulo="Venta confirmada",
            mensaje=f"La venta de mostrador por Bs {venta.total} fue confirmada.",
            tipo="venta_mostrador_confirmada",
            entidad_tipo="VentaMostrador",
            entidad_id=venta.id,
            data={"venta_id": str(venta.id), "estado": venta.estado},
            excluir_usuario_ids=[request.user.id],
        )
        return Response(VentaMostradorSerializer(venta).data)

    @action(detail=False, methods=["post"], url_path="iniciar-pago-tarjeta")
    @transaction.atomic
    def iniciar_pago_tarjeta(self, request, **kwargs):
        payload = request.data
        detalles = payload.get("detalles", [])
        if not detalles:
            return Response({"error": "Debe enviar detalles de venta."}, status=status.HTTP_400_BAD_REQUEST)

        venta = VentaMostrador.objects.create(
            empresa=request.tenant,
            cliente_usuario_id=payload.get("cliente_usuario_id"),
            cliente_nombre_libre=payload.get("cliente_nombre_libre"),
            cliente_documento=payload.get("cliente_documento"),
            vendido_por=request.user,
            estado=EstadoVentaMostrador.BORRADOR,
            subtotal=Decimal("0.00"),
            total=Decimal("0.00"),
        )

        subtotal = Decimal("0.00")
        for d in detalles:
            item_id = d.get("item_inventario_id")
            cantidad = int(d.get("cantidad") or 0)
            precio = Decimal(str(d.get("precio_unitario") or 0))
            if cantidad <= 0 or precio < 0:
                return Response({"error": "Cantidad/precio invalido."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                item = ItemInventario.objects.get(id=item_id, empresa=request.tenant, activo=True)
            except ItemInventario.DoesNotExist:
                return Response({"error": "Item no valido para venta."}, status=status.HTTP_400_BAD_REQUEST)
            if item.stock_actual < cantidad:
                return Response({"error": f"Stock insuficiente para {item.nombre}."}, status=status.HTTP_400_BAD_REQUEST)
            sub = (Decimal(cantidad) * precio).quantize(Decimal("0.01"))
            subtotal += sub
            VentaMostradorDetalle.objects.create(
                empresa=request.tenant,
                venta=venta,
                item_inventario=item,
                cantidad=cantidad,
                precio_unitario=precio,
                subtotal=sub,
            )

        venta.subtotal = subtotal
        venta.total = subtotal
        venta.save(update_fields=["subtotal", "total", "updated_at"])

        codigo_pago = f"STR-{timezone.now().strftime('%Y%m%d%H%M%S')}-{str(venta.id)[:6].upper()}"
        pago = PagoTaller.objects.create(
            empresa=request.tenant,
            tipo_origen=TipoOrigenPagoTaller.VENTA,
            venta=venta,
            tipo_destino="VENTA",
            id_destino=str(venta.id),
            estado=EstadoPagoTaller.PENDIENTE,
            proveedor="STRIPE",
            ambiente="TEST" if settings.STRIPE_MODE == "test" else "LIVE",
            codigo_pago=codigo_pago,
            monto_total=venta.total,
            monto_real=venta.total,
            monto_cobrado=venta.total,
            metodo_pago="TARJETA",
            moneda="BOB",
            referencia=f"STRIPE-{codigo_pago}",
            referencia_externa=f"STRIPE-{codigo_pago}",
            descripcion=payload.get("descripcion") or f"Pago tarjeta venta mostrador {venta.id}",
            registrado_por=request.user,
        )

        frontend_base = (request.headers.get("Origin") or getattr(settings, "PAGOS_RETURN_URL", "") or "http://localhost:5173").rstrip("/")
        success_url = (
            f"{frontend_base}/{request.tenant.slug}/app"
            f"?stripe_sale_result=success&venta_id={venta.id}&pago_taller_id={pago.id}&session_id={{CHECKOUT_SESSION_ID}}"
        )
        cancel_url = (
            f"{frontend_base}/{request.tenant.slug}/app"
            f"?stripe_sale_result=cancel&venta_id={venta.id}&pago_taller_id={pago.id}"
        )

        try:
            currency = (getattr(settings, "STRIPE_CURRENCY", "usd") or "usd").lower()
            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": currency,
                            "product_data": {"name": pago.descripcion},
                            "unit_amount": int((venta.total * Decimal("100")).quantize(Decimal("1"))),
                        },
                        "quantity": 1,
                    }
                ],
                metadata={
                    "pago_taller_id": str(pago.id),
                    "venta_id": str(venta.id),
                    "tenant_slug": request.tenant.slug,
                },
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except Exception as exc:
            pago.estado = EstadoPagoTaller.ERROR
            pago.metadata = {"stripe_error": str(exc)}
            pago.save(update_fields=["estado", "metadata", "updated_at"])
            return Response({"error": f"No se pudo iniciar pago con Stripe: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

        pago.id_pago_proveedor = session.id
        pago.url_pago = session.url
        pago.respuesta_proveedor_raw = {"checkout_session_id": session.id}
        pago.save(update_fields=["id_pago_proveedor", "url_pago", "respuesta_proveedor_raw", "updated_at"])
        notificar_estado_pago(
            pago,
            "Pago con tarjeta iniciado",
            f"Se inició un pago con tarjeta por Bs {venta.total}.",
            "venta_pago_tarjeta_iniciado",
            estado=pago.estado,
            excluir_usuario_ids=[request.user.id],
        )

        return Response(
            {
                "pagoId": str(pago.id),
                "ventaId": str(venta.id),
                "checkoutUrl": session.url,
                "sessionId": session.id,
                "estado": pago.estado,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="confirmar-pago-tarjeta")
    @transaction.atomic
    def confirmar_pago_tarjeta(self, request, **kwargs):
        venta_id = request.data.get("venta_id")
        pago_taller_id = request.data.get("pago_taller_id")
        session_id = request.data.get("session_id")
        if not venta_id or not pago_taller_id or not session_id:
            return Response({"error": "venta_id, pago_taller_id y session_id son requeridos."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            venta = VentaMostrador.objects.get(id=venta_id, empresa=request.tenant)
            pago = PagoTaller.objects.get(
                id=pago_taller_id,
                empresa=request.tenant,
                venta=venta,
                tipo_destino="VENTA",
                id_destino=str(venta.id),
                metodo_pago="TARJETA",
            )
        except (VentaMostrador.DoesNotExist, PagoTaller.DoesNotExist):
            return Response({"error": "Pago de tarjeta no encontrado para la venta."}, status=status.HTTP_404_NOT_FOUND)

        if pago.estado == EstadoPagoTaller.FACTURADO and venta.estado == EstadoVentaMostrador.CONFIRMADA:
            return Response({"ok": True, "estado": pago.estado}, status=status.HTTP_200_OK)
        if pago.estado in [EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO, EstadoPagoTaller.ANULADO]:
            return Response({"error": f"El pago no puede confirmarse en estado {pago.estado}."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except Exception as exc:
            return Response({"error": f"No se pudo consultar Stripe: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

        if session.id != pago.id_pago_proveedor:
            return Response({"error": "La sesion de Stripe no coincide con el pago."}, status=status.HTTP_400_BAD_REQUEST)
        if session.payment_status != "paid":
            return Response({"error": f"El pago no esta confirmado en Stripe. Estado: {session.payment_status}"}, status=status.HTTP_400_BAD_REQUEST)

        if pago.estado != EstadoPagoTaller.FACTURADO:
            pago.estado = EstadoPagoTaller.CONFIRMADO
            pago.monto_pagado = pago.monto_total
            pago.fecha_pago = timezone.now()
            pago.recibido_at = pago.fecha_pago
            pago.save(update_fields=["estado", "monto_pagado", "fecha_pago", "recibido_at", "updated_at"])
            self._registrar_movimiento_caja_si_aplica(request, pago)

        try:
            self._confirmar_venta_stock(request, venta)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not hasattr(pago, "factura"):
            Factura.objects.create(
                empresa=request.tenant,
                pago_taller=pago,
                numero=f"FAC-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                nit_razon_social=request.data.get("nit_razon_social", ""),
                total=pago.monto_total,
                archivo_pdf_url=request.data.get("archivo_pdf_url", ""),
            )
            pago.estado = EstadoPagoTaller.FACTURADO
            pago.save(update_fields=["estado", "updated_at"])

        notificar_estado_pago(
            pago,
            "Pago con tarjeta confirmado",
            f"Se confirmó el pago con tarjeta de la venta por Bs {pago.monto_total}.",
            "venta_pago_tarjeta_confirmado",
            estado=pago.estado,
            excluir_usuario_ids=[request.user.id],
        )
        notificar_estado_pago(
            venta,
            "Venta cobrada y confirmada",
            f"La venta {venta.id} quedó confirmada y cobrada por tarjeta.",
            "venta_confirmada_tarjeta",
            estado=venta.estado,
            excluir_usuario_ids=[request.user.id],
        )

        return Response(
            {
                "ok": True,
                "estado": pago.estado,
                "venta_estado": venta.estado,
                "venta_id": str(venta.id),
            },
            status=status.HTTP_200_OK,
        )


class PagoTallerViewSet(viewsets.ModelViewSet):
    serializer_class = PagoTallerSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarCajaPagos]

    def get_permissions(self):
        if self.action in ["callback_libelula"]:
            return [permissions.AllowAny()]
        if self.action in ["crear_qr", "consultar_estado_qr"]:
            return [IsAuthenticatedTenant()]
        return [permission() for permission in self.permission_classes]

    def get_queryset(self):
        qs = PagoTaller.objects.filter(empresa=self.request.tenant).order_by("-created_at")
        estado = self.request.query_params.get("estado")
        tipo_origen = self.request.query_params.get("tipo_origen")
        if estado:
            qs = qs.filter(estado=estado)
        if tipo_origen:
            qs = qs.filter(tipo_origen=tipo_origen)
        return qs

    def _obtener_o_crear_caja_activa(self, request):
        caja = CajaUsuario.objects.filter(
            empresa=request.tenant,
            administrativo=request.user,
            activa=True,
        ).first()
        if caja:
            return caja
        return CajaUsuario.objects.create(
            empresa=request.tenant,
            administrativo=request.user,
            nombre=f"Caja {request.user.nombres}",
            activa=True,
        )

    def perform_create(self, serializer):
        serializer.save(empresa=self.request.tenant, registrado_por=self.request.user)

    def _validar_confirmacion(self, pago, monto_pagado: Decimal, moneda: str):
        if pago.estado == EstadoPagoTaller.CONFIRMADO:
            return "ya_confirmado"
        if pago.estado in [EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO]:
            return "estado_final"
        ahora = timezone.now()
        if pago.fecha_expiracion and ahora > pago.fecha_expiracion:
            pago.estado = EstadoPagoTaller.VENCIDO
            pago.save(update_fields=["estado", "updated_at"])
            return "vencido"
        if (moneda or "").upper() != "BOB":
            pago.estado = EstadoPagoTaller.RECHAZADO
            pago.save(update_fields=["estado", "updated_at"])
            return "moneda_invalida"
        esperado = monto_esperado_para_validacion(pago)
        if Decimal(str(monto_pagado)).quantize(Decimal("0.01")) != esperado:
            pago.estado = EstadoPagoTaller.MONTO_INCORRECTO
            pago.monto_pagado = Decimal(str(monto_pagado)).quantize(Decimal("0.01"))
            pago.save(update_fields=["estado", "monto_pagado", "updated_at"])
            return "monto_incorrecto"
        pago.estado = EstadoPagoTaller.CONFIRMADO
        pago.monto_pagado = Decimal(str(monto_pagado)).quantize(Decimal("0.01"))
        pago.fecha_pago = ahora
        pago.recibido_at = ahora
        pago.save(update_fields=["estado", "monto_pagado", "fecha_pago", "recibido_at", "updated_at"])
        return "confirmado"

    def _aplicar_confirmacion_simulada(self, pago):
        if pago.estado == EstadoPagoTaller.CONFIRMADO:
            return "ya_confirmado"
        if pago.estado in [EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO]:
            return "estado_final"
        ahora = timezone.now()
        if pago.fecha_expiracion and ahora > pago.fecha_expiracion:
            pago.estado = EstadoPagoTaller.VENCIDO
            pago.save(update_fields=["estado", "updated_at"])
            return "vencido"

        monto_confirmado = monto_esperado_para_validacion(pago)
        pago.estado = EstadoPagoTaller.CONFIRMADO
        pago.monto_pagado = monto_confirmado
        pago.fecha_pago = ahora
        pago.recibido_at = ahora
        pago.save(update_fields=["estado", "monto_pagado", "fecha_pago", "recibido_at", "updated_at"])
        return "confirmado"

    @action(detail=False, methods=["post"], url_path="crear-qr")
    @transaction.atomic
    def crear_qr(self, request, **kwargs):
        try:
            tipo_destino = (request.data.get("tipo_destino") or "").upper().strip()
            id_destino = str(request.data.get("id_destino") or "").strip()
            monto_real = Decimal(str(request.data.get("monto_real") or "0")).quantize(Decimal("0.01"))
            descripcion = (request.data.get("descripcion") or f"Pago {tipo_destino}").strip()
            moneda = (request.data.get("moneda") or "BOB").upper().strip()
            fecha_expiracion = parse_datetime(request.data.get("fecha_expiracion") or "")
            if not fecha_expiracion:
                return Response({"error": "fecha_expiracion invalida."}, status=status.HTTP_400_BAD_REQUEST)
            if fecha_expiracion <= timezone.now():
                return Response({"error": "fecha_expiracion debe ser futura."}, status=status.HTTP_400_BAD_REQUEST)
            if moneda != "BOB":
                return Response({"error": "Solo se permite moneda BOB."}, status=status.HTTP_400_BAD_REQUEST)
            if not tipo_destino or not id_destino:
                return Response({"error": "tipo_destino e id_destino son obligatorios."}, status=status.HTTP_400_BAD_REQUEST)
            validar_monto_real(monto_real)
            ambiente = getattr(settings, "PAGOS_MODO", "PRUEBA_REAL").upper()
            monto_cobrado = calcular_monto_cobrado(monto_real, ambiente)
            if getattr(settings, "PAGOS_QR_SIMULADO", True):
                monto_cobrado = monto_real
            referencia_externa = generar_referencia_externa(ambiente, tipo_destino, id_destino)
            codigo_pago = f"PAGO-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
            callback_url = getattr(settings, "PAGOS_CALLBACK_URL", "")
            return_url = getattr(settings, "PAGOS_RETURN_URL", "")

            pago = PagoTaller.objects.create(
                empresa=request.tenant,
                tipo_origen=TipoOrigenPagoTaller.CITA if tipo_destino in ["CITA", "PRESUPUESTO"] else TipoOrigenPagoTaller.VENTA,
                estado=EstadoPagoTaller.PENDIENTE,
                monto_total=monto_real,
                monto_real=monto_real,
                monto_cobrado=monto_cobrado,
                metodo_pago="QR",
                moneda=moneda,
                referencia=referencia_externa,
                referencia_externa=referencia_externa,
                codigo_pago=codigo_pago,
                proveedor="LIBELULA_QR",
                ambiente=ambiente,
                tipo_destino=tipo_destino,
                id_destino=id_destino,
                descripcion=descripcion,
                fecha_expiracion=fecha_expiracion,
                registrado_por=request.user if request.user and request.user.is_authenticated else None,
                metadata={"evento": "PAGO_CREADO"},
            )

            if getattr(settings, "PAGOS_QR_SIMULADO", True):
                token_simulador = uuid.uuid4().hex
                frontend_base = (getattr(settings, "PAGOS_SIMULADOR_FRONTEND_URL", "") or "http://localhost:5173").rstrip("/")
                url_simulada = f"{frontend_base}/pagos/simulador/{pago.codigo_pago}/{token_simulador}"
                pago.url_pago = url_simulada
                pago.qr_imagen_url = f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={quote(url_simulada)}"
                pago.qr_payload = {"url": url_simulada}
                pago.metadata = {**(pago.metadata or {}), "simulado": True, "sim_token": token_simulador}
                pago.respuesta_proveedor_raw = {"simulado": True, "url_pago": url_simulada}
                pago.save(update_fields=["url_pago", "qr_imagen_url", "qr_payload", "metadata", "respuesta_proveedor_raw", "updated_at"])
            else:
                cliente = LibelulaPaymentClient()
                resp = cliente.crear_cobro(
                    monto_cobrado=monto_cobrado,
                    moneda=moneda,
                    descripcion=descripcion,
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
                    "id_pago_proveedor", "id_transaccion_proveedor", "qr_imagen_url", "qr_imagen_base64",
                    "url_pago", "qr_payload", "respuesta_proveedor_raw", "updated_at"
                ])
            notificar_estado_pago(
                pago,
                "Pago QR generado",
                f"Se generó un pago QR por Bs {pago.monto_total}.",
                "pago_qr_generado",
                estado=pago.estado,
                excluir_usuario_ids=[request.user.id],
            )
            return Response(PagoTallerSerializer(pago).data, status=status.HTTP_201_CREATED)
        except PagoQRError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"error": f"Error creando pago QR: {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["get"], url_path="estado-qr")
    @transaction.atomic
    def consultar_estado_qr(self, request, pk=None, **kwargs):
        pago = self.get_object()
        if pago.estado == EstadoPagoTaller.PENDIENTE and pago.fecha_expiracion and timezone.now() > pago.fecha_expiracion:
            pago.estado = EstadoPagoTaller.VENCIDO
            pago.save(update_fields=["estado", "updated_at"])
            notificar_estado_pago(
                pago,
                "Pago QR vencido",
                f"El pago {pago.codigo_pago or pago.id} venció sin confirmación.",
                "pago_qr_vencido",
                estado=pago.estado,
            )
        if (
            pago.estado == EstadoPagoTaller.PENDIENTE
            and pago.id_pago_proveedor
            and not getattr(settings, "PAGOS_QR_SIMULADO", True)
        ):
            try:
                cliente = LibelulaPaymentClient()
                estado_proveedor = cliente.consultar_estado(pago.id_pago_proveedor)
                estado_norm = estado_desde_proveedor(estado_proveedor.get("estado_proveedor"))
                if estado_norm == EstadoPagoTaller.CONFIRMADO:
                    self._validar_confirmacion(
                        pago,
                        Decimal(str(estado_proveedor.get("monto_pagado") or "0")),
                        estado_proveedor.get("moneda") or pago.moneda,
                    )
                    if pago.estado == EstadoPagoTaller.CONFIRMADO:
                        notificar_estado_pago(
                            pago,
                            "Pago QR confirmado",
                            f"Se confirmó el pago {pago.codigo_pago or pago.id} por Bs {pago.monto_total}.",
                            "pago_qr_confirmado_consulta",
                            estado=pago.estado,
                        )
                elif estado_norm in [EstadoPagoTaller.FALLIDO, EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO]:
                    pago.estado = estado_norm
                    pago.respuesta_proveedor_raw = estado_proveedor.get("raw")
                    pago.save(update_fields=["estado", "respuesta_proveedor_raw", "updated_at"])
                    notificar_estado_pago(
                        pago,
                        "Pago QR actualizado",
                        f"El pago {pago.codigo_pago or pago.id} cambió a estado {pago.estado}.",
                        "pago_qr_estado_consulta",
                        estado=pago.estado,
                    )
            except Exception:
                pass
        return Response(PagoTallerSerializer(pago).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="simular-confirmacion")
    @transaction.atomic
    def simular_confirmacion(self, request, pk=None, **kwargs):
        pago = self.get_object()
        accion = (request.data.get("accion") or "confirmar").lower()
        if accion == "rechazar":
            if pago.estado == EstadoPagoTaller.PENDIENTE:
                pago.estado = EstadoPagoTaller.FALLIDO
                pago.save(update_fields=["estado", "updated_at"])
                notificar_estado_pago(
                    pago,
                    "Pago QR rechazado",
                    f"El pago {pago.codigo_pago or pago.id} fue rechazado.",
                    "pago_qr_rechazado_simulado",
                    estado=pago.estado,
                )
            return Response({"ok": True, "estado": pago.estado}, status=status.HTTP_200_OK)
        resultado = self._aplicar_confirmacion_simulada(pago)
        if pago.estado == EstadoPagoTaller.CONFIRMADO:
            notificar_estado_pago(
                pago,
                "Pago QR confirmado",
                f"Se confirmó el pago {pago.codigo_pago or pago.id} por Bs {pago.monto_total}.",
                "pago_qr_confirmado_simulado",
                estado=pago.estado,
            )
        return Response({"ok": True, "estado": pago.estado, "resultado": resultado}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="estado")
    def estado_por_codigo(self, request, **kwargs):
        codigo_pago = (request.query_params.get("codigo_pago") or "").strip()
        if not codigo_pago:
            return Response({"error": "codigo_pago es requerido"}, status=status.HTTP_400_BAD_REQUEST)
        pago = PagoTaller.objects.filter(empresa=request.tenant, codigo_pago=codigo_pago).first()
        if not pago:
            return Response({"error": "Pago no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        if pago.estado == EstadoPagoTaller.PENDIENTE and pago.fecha_expiracion and timezone.now() > pago.fecha_expiracion:
            pago.estado = EstadoPagoTaller.VENCIDO
            pago.save(update_fields=["estado", "updated_at"])
        return Response(PagoTallerSerializer(pago).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="callback/libelula")
    @transaction.atomic
    def callback_libelula(self, request, **kwargs):
        payload = request.data if isinstance(request.data, dict) else {}
        result = procesar_callback_libelula(payload, request.headers, tenant=request.tenant)
        return Response(result["body"], status=result["status"])

    @action(detail=True, methods=["post"], url_path="marcar-recibido")
    @transaction.atomic
    def marcar_recibido(self, request, pk=None, **kwargs):
        pago = self.get_object()
        if pago.estado in [EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.CONFIRMADO]:
            return Response({"error": "El pago ya fue recibido."}, status=status.HTTP_400_BAD_REQUEST)
        if pago.estado in [EstadoPagoTaller.ANULADO, EstadoPagoTaller.CANCELADO]:
            return Response({"error": "No se puede recibir un pago anulado."}, status=status.HTTP_400_BAD_REQUEST)

        pago.estado = EstadoPagoTaller.CONFIRMADO
        pago.recibido_at = timezone.now()
        pago.fecha_pago = pago.recibido_at
        pago.monto_pagado = pago.monto_total
        pago.save(update_fields=["estado", "recibido_at", "fecha_pago", "monto_pagado", "updated_at"])

        caja = self._obtener_o_crear_caja_activa(request)
        cliente = "Cliente"
        if pago.cita and pago.cita.cliente:
            cliente = f"{pago.cita.cliente.nombres} {pago.cita.cliente.apellidos or ''}".strip() or "Cliente"
        elif pago.venta:
            if pago.venta.cliente_usuario:
                cliente = f"{pago.venta.cliente_usuario.nombres} {pago.venta.cliente_usuario.apellidos or ''}".strip() or "Cliente"
            else:
                cliente = pago.venta.cliente_nombre_libre or "Cliente"
        MovimientoCaja.objects.create(
            empresa=request.tenant,
            caja=caja,
            tipo=TipoMovimientoCaja.INGRESO,
            concepto=f"Ingreso pago taller - {cliente}",
            monto=pago.monto_total,
            pago_taller=pago,
            registrado_por=request.user,
        )
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=destinatarios_pago_o_venta(pago),
            titulo="Pago recibido",
            mensaje=f"Se confirmó un pago por Bs {pago.monto_total}.",
            tipo="pago_taller_recibido",
            entidad_tipo="PagoTaller",
            entidad_id=pago.id,
            data={"pago_id": str(pago.id), "estado": pago.estado},
            excluir_usuario_ids=[request.user.id],
        )

        return Response(PagoTallerSerializer(pago).data)


class FacturaViewSet(viewsets.ModelViewSet):
    serializer_class = FacturaSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarCajaPagos]

    def get_queryset(self):
        return Factura.objects.filter(empresa=self.request.tenant).order_by("-created_at")

    @action(detail=False, methods=["get"], url_path="pagos-disponibles")
    def pagos_disponibles(self, request, **kwargs):
        pagos = (
            PagoTaller.objects.filter(empresa=request.tenant, estado__in=[EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.CONFIRMADO])
            .select_related("cita__cliente", "venta__cliente_usuario")
            .order_by("-created_at")
        )
        data = []
        for p in pagos:
            if hasattr(p, "factura"):
                continue
            cliente = "-"
            if p.cita and p.cita.cliente:
                cliente = f"{p.cita.cliente.nombres} {p.cita.cliente.apellidos or ''}".strip()
            elif p.venta:
                if p.venta.cliente_usuario:
                    cliente = f"{p.venta.cliente_usuario.nombres} {p.venta.cliente_usuario.apellidos or ''}".strip()
                else:
                    cliente = p.venta.cliente_nombre_libre or "-"
            data.append(
                {
                    "id": str(p.id),
                    "codigo_pago": p.codigo_pago,
                    "estado": p.estado,
                    "metodo_pago": p.metodo_pago,
                    "moneda": p.moneda,
                    "monto_total": float(p.monto_total or 0),
                    "fecha_pago": p.fecha_pago.isoformat() if p.fecha_pago else None,
                    "tipo_origen": p.tipo_origen,
                    "cliente": cliente,
                    "referencia": p.referencia,
                }
            )
        return Response(data, status=status.HTTP_200_OK)

    def _build_factura_context(self, factura):
        pago = factura.pago_taller
        empresa = factura.empresa
        cliente = "-"
        documento = "-"
        detalle_origen = "-"
        lineas = []

        if pago and pago.cita and pago.cita.cliente:
            cliente = f"{pago.cita.cliente.nombres} {pago.cita.cliente.apellidos or ''}".strip()
            documento = pago.cita.cliente.email or "-"
            detalle_origen = f"Cita {pago.cita.id}"
            lineas.append(
                {
                    "descripcion": f"Servicio de taller ({detalle_origen})",
                    "cantidad": 1,
                    "precio_unitario": float(pago.monto_total or 0),
                    "subtotal": float(pago.monto_total or 0),
                }
            )
        elif pago and pago.venta:
            if pago.venta.cliente_usuario:
                cliente = f"{pago.venta.cliente_usuario.nombres} {pago.venta.cliente_usuario.apellidos or ''}".strip()
                documento = pago.venta.cliente_usuario.email or "-"
            else:
                cliente = pago.venta.cliente_nombre_libre or "-"
                documento = pago.venta.cliente_documento or "-"
            detalle_origen = f"Venta {pago.venta.id}"
            for det in pago.venta.detalles.select_related("item_inventario").all():
                lineas.append(
                    {
                        "descripcion": det.item_inventario.nombre if det.item_inventario else "Item",
                        "cantidad": int(det.cantidad or 0),
                        "precio_unitario": float(det.precio_unitario or 0),
                        "subtotal": float(det.subtotal or 0),
                    }
                )

        if not lineas:
            lineas.append(
                {
                    "descripcion": "Servicio/venta registrado",
                    "cantidad": 1,
                    "precio_unitario": float(factura.total or 0),
                    "subtotal": float(factura.total or 0),
                }
            )

        project_root = Path(__file__).resolve().parents[4]
        logo_candidates = [
            project_root / "frontend" / "public" / "favicon.png",
            project_root / "frontend" / "src" / "assets" / "logoapp.png",
        ]
        logo_path = next((str(p) for p in logo_candidates if p.exists()), None)
        initials = "".join([part[0] for part in empresa.nombre.split()[:2]]).upper() or "EM"

        return {
            "empresa_nombre": empresa.nombre,
            "empresa_slug": empresa.slug,
            "empresa_logo_path": logo_path,
            "empresa_initials": initials,
            "numero": factura.numero,
            "fecha_emision": timezone.localtime(factura.fecha_emision).strftime("%d/%m/%Y %H:%M"),
            "cliente": cliente,
            "documento": documento,
            "nit_razon_social": factura.nit_razon_social or "-",
            "origen": detalle_origen,
            "metodo_pago": pago.metodo_pago if pago else "-",
            "estado_pago": pago.estado if pago else "-",
            "moneda": pago.moneda if pago else "BOB",
            "total": f"{Decimal(factura.total):.2f}",
            "pago_id": str(pago.id) if pago else "-",
            "lineas": lineas,
        }
    def _render_factura_html(self, factura):
        c = self._build_factura_context(factura)
        rows = "".join(
            [
                f"<tr><td>{idx + 1}</td><td>{ln['descripcion']}</td><td>{ln['cantidad']}</td><td>{ln['precio_unitario']:.2f}</td><td>{ln['subtotal']:.2f}</td></tr>"
                for idx, ln in enumerate(c["lineas"])
            ]
        )
        return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Factura {c['numero']}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #111827; }}
    .header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }}
    .logo {{ width: 56px; height: 56px; border-radius: 50%; background: #b91c1c; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px; }}
    .brand-row {{ display: flex; align-items: center; gap: 10px; }}
    .brand h1 {{ margin: 0 0 4px 0; font-size: 24px; }}
    .brand p {{ margin: 2px 0; color: #4b5563; font-size: 13px; }}
    .chip {{ background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; font-size: 12px; }}
    .title {{ margin: 10px 0 18px 0; font-size: 20px; font-weight: bold; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 10px; font-size: 13px; text-align: left; }}
    th {{ background: #f9fafb; }}
    .total {{ margin-top: 14px; text-align: right; font-weight: bold; font-size: 18px; }}
    .footer {{ margin-top: 30px; font-size: 11px; color: #6b7280; }}
  </style>
</head>
<body>
  <div class="header">
    <div class="brand">
      <div class="brand-row">
        <div class="logo">{c['empresa_initials']}</div>
        <div>
          <h1>{c['empresa_nombre']}</h1>
          <p>Tenant: {c['empresa_slug']}</p>
          <p>Comprobante: {c['numero']}</p>
        </div>
      </div>
    </div>
    <div class="chip">
      <div><strong>Fecha:</strong> {c['fecha_emision']}</div>
      <div><strong>Estado pago:</strong> {c['estado_pago']}</div>
      <div><strong>Método:</strong> {c['metodo_pago']}</div>
    </div>
  </div>
  <div class="title">Factura / Recibo</div>
  <table>
    <tbody>
      <tr><th>Cliente</th><td>{c['cliente']}</td><th>Documento</th><td>{c['documento']}</td></tr>
      <tr><th>NIT / Razón social</th><td>{c['nit_razon_social']}</td><th>Pago asociado</th><td>{c['pago_id']}</td></tr>
      <tr><th>Origen</th><td>{c['origen']}</td><th>Moneda</th><td>{c['moneda']}</td></tr>
    </tbody>
  </table>
  <table>
    <thead>
      <tr><th>#</th><th>Detalle</th><th>Cantidad</th><th>Precio Unit.</th><th>Subtotal</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <div class="total">TOTAL: {c['total']} {c['moneda']}</div>
  <div class="footer">
    Documento generado por la plataforma web para la empresa autenticada.
  </div>
</body>
</html>"""
    def _build_simple_pdf(self, factura):
        c = self._build_factura_context(factura)
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.pdfgen import canvas

            buffer = BytesIO()
            pdf = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4

            pdf.setFillColorRGB(0.72, 0.11, 0.11)
            pdf.rect(0, height - 40 * mm, width, 40 * mm, fill=1, stroke=0)

            logo_x = 15 * mm
            logo_y = height - 32 * mm
            if c["empresa_logo_path"]:
                try:
                    pdf.drawImage(c["empresa_logo_path"], logo_x, logo_y, width=18 * mm, height=18 * mm, mask="auto")
                except Exception:
                    pass
            pdf.setFillColor(colors.white)
            pdf.circle(logo_x + 9 * mm, logo_y + 9 * mm, 9 * mm, fill=1, stroke=0)
            pdf.setFillColorRGB(0.72, 0.11, 0.11)
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawCentredString(logo_x + 9 * mm, logo_y + 8.5 * mm, c["empresa_initials"])

            pdf.setFillColor(colors.white)
            pdf.setFont("Helvetica-Bold", 15)
            pdf.drawString(40 * mm, height - 18 * mm, c["empresa_nombre"])
            pdf.setFont("Helvetica", 9)
            pdf.drawString(40 * mm, height - 24 * mm, f"Tenant: {c['empresa_slug']}")
            pdf.drawString(40 * mm, height - 29 * mm, f"Comprobante: {c['numero']}")

            pdf.setFont("Helvetica-Bold", 13)
            pdf.setFillColor(colors.black)
            pdf.drawString(15 * mm, height - 50 * mm, "FACTURA / RECIBO")

            y = height - 58 * mm
            pdf.setFont("Helvetica", 9)
            meta_rows = [
                f"Fecha emision: {c['fecha_emision']}",
                f"Cliente: {c['cliente']}",
                f"Documento: {c['documento']}",
                f"NIT / Razon social: {c['nit_razon_social']}",
                f"Pago asociado: {c['pago_id']}",
                f"Origen: {c['origen']}",
                f"Metodo pago: {c['metodo_pago']}",
                f"Estado pago: {c['estado_pago']}",
            ]
            for row in meta_rows:
                pdf.drawString(15 * mm, y, row)
                y -= 5 * mm

            table_y_top = y - 3 * mm
            cols = [15 * mm, 30 * mm, 110 * mm, 140 * mm, 170 * mm, 195 * mm]
            row_h = 7 * mm
            pdf.setFillColorRGB(0.95, 0.95, 0.95)
            pdf.rect(cols[0], table_y_top - row_h, cols[-1] - cols[0], row_h, fill=1, stroke=1)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica-Bold", 8.5)
            headers = ["#", "Detalle", "Cant.", "P. Unit.", "Subtotal"]
            for i, h in enumerate(headers):
                pdf.drawString(cols[i] + 2, table_y_top - 5.5 * mm, h)

            pdf.setFont("Helvetica", 8.5)
            current_y = table_y_top - row_h
            for idx, ln in enumerate(c["lineas"], start=1):
                current_y -= row_h
                if current_y < 30 * mm:
                    pdf.showPage()
                    current_y = height - 30 * mm
                pdf.rect(cols[0], current_y, cols[-1] - cols[0], row_h, fill=0, stroke=1)
                pdf.drawString(cols[0] + 2, current_y + 2.5 * mm, str(idx))
                pdf.drawString(cols[1] + 2, current_y + 2.5 * mm, str(ln["descripcion"])[:55])
                pdf.drawRightString(cols[3] - 2, current_y + 2.5 * mm, str(ln["cantidad"]))
                pdf.drawRightString(cols[4] - 2, current_y + 2.5 * mm, f"{float(ln['precio_unitario']):.2f}")
                pdf.drawRightString(cols[5] - 2, current_y + 2.5 * mm, f"{float(ln['subtotal']):.2f}")

            pdf.setFont("Helvetica-Bold", 12)
            pdf.drawRightString(195 * mm, current_y - 8 * mm, f"TOTAL: {c['total']} {c['moneda']}")
            pdf.setFont("Helvetica-Oblique", 7.5)
            pdf.setFillColor(colors.grey)
            pdf.drawString(15 * mm, 12 * mm, "Documento generado por la plataforma web para la empresa autenticada.")
            pdf.save()
            return buffer.getvalue()
        except Exception:
            pass

        lines = [
            f"FACTURA / RECIBO - {c['numero']}",
            f"Empresa: {c['empresa_nombre']} ({c['empresa_slug']})",
            f"Fecha emision: {c['fecha_emision']}",
            f"Cliente: {c['cliente']}",
            f"Documento: {c['documento']}",
            f"NIT / Razon social: {c['nit_razon_social']}",
            f"Pago asociado: {c['pago_id']}",
            f"Origen: {c['origen']}",
            f"Metodo pago: {c['metodo_pago']}",
            f"Estado pago: {c['estado_pago']}",
            f"TOTAL: {c['total']} {c['moneda']}",
        ]

        def esc(text):
            return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        y = 800
        content_stream = ["BT", "/F1 11 Tf"]
        for line in lines:
            content_stream.append(f"72 {y} Td ({esc(line)}) Tj")
            content_stream.append("0 -18 Td")
            y -= 18
        content_stream.append("ET")
        stream_body = "\n".join(content_stream).encode("latin-1", errors="replace")

        objects = []
        objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
        objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
        objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n")
        objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
        objects.append(
            b"5 0 obj << /Length " + str(len(stream_body)).encode("ascii") + b" >> stream\n" + stream_body + b"\nendstream endobj\n"
        )

        buffer = BytesIO()
        buffer.write(b"%PDF-1.4\n")
        xref_positions = [0]
        for obj in objects:
            xref_positions.append(buffer.tell())
            buffer.write(obj)
        xref_start = buffer.tell()
        buffer.write(f"xref\n0 {len(xref_positions)}\n".encode("ascii"))
        buffer.write(b"0000000000 65535 f \n")
        for pos in xref_positions[1:]:
            buffer.write(f"{pos:010d} 00000 n \n".encode("ascii"))
        buffer.write(
            f"trailer << /Size {len(xref_positions)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF".encode("ascii")
        )
        return buffer.getvalue()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        pago_id = request.data.get("pago_taller")
        if not pago_id:
            return Response({"error": "pago_taller es requerido."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pago = PagoTaller.objects.get(id=pago_id, empresa=request.tenant)
        except PagoTaller.DoesNotExist:
            return Response({"error": "Pago no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        if pago.estado not in [EstadoPagoTaller.RECIBIDO, EstadoPagoTaller.CONFIRMADO]:
            return Response({"error": "Solo se puede facturar pago recibido."}, status=status.HTTP_400_BAD_REQUEST)
        if hasattr(pago, "factura"):
            return Response({"error": "El pago ya tiene factura."}, status=status.HTTP_400_BAD_REQUEST)

        numero = request.data.get("numero") or f"FAC-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        if Factura.objects.filter(empresa=request.tenant, numero=numero).exists():
            return Response({"error": "Ya existe una factura con ese numero en esta empresa."}, status=status.HTTP_400_BAD_REQUEST)
        nit_razon_social = (request.data.get("nit_razon_social") or "").strip()
        if not nit_razon_social:
            return Response({"error": "nit_razon_social es requerido."}, status=status.HTTP_400_BAD_REQUEST)
        factura = Factura.objects.create(
            empresa=request.tenant,
            pago_taller=pago,
            numero=numero,
            nit_razon_social=nit_razon_social,
            total=pago.monto_total,
            archivo_pdf_url=request.data.get("archivo_pdf_url", ""),
        )
        factura.html_generado = self._render_factura_html(factura)
        factura.save(update_fields=["html_generado"])
        pago.estado = EstadoPagoTaller.FACTURADO
        pago.save(update_fields=["estado", "updated_at"])
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=destinatarios_pago_o_venta(factura),
            titulo="Factura emitida",
            mensaje=f"Se emitió la factura {factura.numero} por Bs {factura.total}.",
            tipo="factura_emitida",
            entidad_tipo="Factura",
            entidad_id=factura.id,
            data={"factura_id": str(factura.id), "numero": factura.numero},
            excluir_usuario_ids=[request.user.id],
        )
        return Response(FacturaSerializer(factura).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="visualizar")
    def visualizar(self, request, pk=None, **kwargs):
        factura = self.get_object()
        pdf_bytes = self._build_simple_pdf(factura)
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{factura.numero}.pdf"'
        return resp

    @action(detail=True, methods=["get"], url_path="descargar")
    def descargar(self, request, pk=None, **kwargs):
        factura = self.get_object()
        formato = (request.query_params.get("formato") or "pdf").lower()
        html = self._render_factura_html(factura)
        filename_base = f"factura_{factura.numero}"

        if formato == "pdf":
            resp = HttpResponse(self._build_simple_pdf(factura), content_type="application/pdf")
            resp["Content-Disposition"] = f'attachment; filename="{filename_base}.pdf"'
            return resp

        if formato == "html":
            resp = HttpResponse(html, content_type="text/html; charset=utf-8")
            resp["Content-Disposition"] = f'attachment; filename="{filename_base}.html"'
            return resp

        if formato == "csv":
            c = self._build_factura_context(factura)
            resp = HttpResponse(content_type="text/csv; charset=utf-8")
            resp["Content-Disposition"] = f'attachment; filename="{filename_base}.csv"'
            writer = csv.writer(resp)
            writer.writerow(["campo", "valor"])
            for key, value in c.items():
                writer.writerow([key, value])
            return resp

        if formato in ["excel", "xlsx", "xls"]:
            c = self._build_factura_context(factura)
            table = "".join([f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in c.items()])
            excel_html = f"<table><thead><tr><th>Campo</th><th>Valor</th></tr></thead><tbody>{table}</tbody></table>"
            resp = HttpResponse(excel_html, content_type="application/vnd.ms-excel; charset=utf-8")
            resp["Content-Disposition"] = f'attachment; filename="{filename_base}.xls"'
            return resp

        if formato in ["word", "doc"]:
            resp = HttpResponse(html, content_type="application/msword; charset=utf-8")
            resp["Content-Disposition"] = f'attachment; filename="{filename_base}.doc"'
            return resp

        if formato == "docx":
            resp = HttpResponse(html, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            resp["Content-Disposition"] = f'attachment; filename="{filename_base}.docx"'
            return resp

        return Response({"error": "Formato no soportado. Usa pdf, html, csv, excel o word/doc/docx."}, status=status.HTTP_400_BAD_REQUEST)


class CajaUsuarioViewSet(viewsets.ModelViewSet):
    serializer_class = CajaUsuarioSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarCajaPagos]

    def get_queryset(self):
        return CajaUsuario.objects.filter(empresa=self.request.tenant).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(empresa=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="mi-caja")
    def mi_caja(self, request, **kwargs):
        caja = CajaUsuario.objects.filter(
            empresa=request.tenant,
            administrativo=request.user,
            activa=True,
        ).first()
        if not caja:
            return Response({"error": "No tienes caja activa."}, status=status.HTTP_404_NOT_FOUND)

        movs_qs = MovimientoCaja.objects.filter(empresa=request.tenant, caja=caja)
        ingresos = movs_qs.filter(tipo=TipoMovimientoCaja.INGRESO).aggregate(total=Sum("monto")).get("total") or Decimal("0")
        egresos = movs_qs.filter(tipo=TipoMovimientoCaja.EGRESO).aggregate(total=Sum("monto")).get("total") or Decimal("0")
        ajustes = movs_qs.filter(tipo=TipoMovimientoCaja.AJUSTE).aggregate(total=Sum("monto")).get("total") or Decimal("0")
        saldo = ingresos - egresos + ajustes
        movs = movs_qs.order_by("-created_at")[:50]
        return Response(
            {
                "caja": CajaUsuarioSerializer(caja).data,
                "resumen": {
                    "ingresos": float(ingresos),
                    "egresos": float(egresos),
                    "ajustes": float(ajustes),
                    "saldo": float(saldo),
                },
                "movimientos": MovimientoCajaSerializer(movs, many=True).data,
            }
        )


class MovimientoCajaViewSet(viewsets.ModelViewSet):
    serializer_class = MovimientoCajaSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarCajaPagos]

    def get_queryset(self):
        qs = MovimientoCaja.objects.filter(empresa=self.request.tenant).order_by("-created_at")
        caja = self.request.query_params.get("caja")
        tipo = self.request.query_params.get("tipo")
        if caja:
            qs = qs.filter(caja_id=caja)
        if tipo:
            qs = qs.filter(tipo=tipo)
        return qs

    def perform_create(self, serializer):
        serializer.save(empresa=self.request.tenant, registrado_por=self.request.user)


class LibelulaWebhookGlobalView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        payload = request.data if isinstance(request.data, dict) else {}
        result = procesar_callback_libelula(payload, request.headers, tenant=None)
        return Response(result["body"], status=result["status"])


class PagoQRSimuladorPublicView(APIView):
    permission_classes = [permissions.AllowAny]

    def _buscar_pago(self, codigo_pago, token):
        pago = PagoTaller.objects.filter(codigo_pago=codigo_pago).order_by("-created_at").first()
        if not pago:
            return None
        metadata = pago.metadata or {}
        if metadata.get("sim_token") != token:
            return None
        return pago

    def get(self, request, codigo_pago, token, *args, **kwargs):
        pago = self._buscar_pago(codigo_pago, token)
        if not pago:
            return Response({"error": "Pago simulado no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        if pago.estado == EstadoPagoTaller.PENDIENTE and pago.fecha_expiracion and timezone.now() > pago.fecha_expiracion:
            pago.estado = EstadoPagoTaller.VENCIDO
            pago.save(update_fields=["estado", "updated_at"])
        return Response(
            {
                "codigoPago": pago.codigo_pago,
                "estado": pago.estado,
                "descripcion": pago.descripcion,
                "montoReal": str(pago.monto_real or pago.monto_total),
                "montoCobrado": str(pago.monto_cobrado or pago.monto_total),
                "montoPagado": str(pago.monto_pagado) if pago.monto_pagado is not None else None,
                "moneda": pago.moneda,
                "fechaExpiracion": pago.fecha_expiracion.isoformat() if pago.fecha_expiracion else None,
                "ambiente": pago.ambiente,
                "simulado": True,
            },
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    def post(self, request, codigo_pago, token, *args, **kwargs):
        pago = self._buscar_pago(codigo_pago, token)
        if not pago:
            return Response({"error": "Pago simulado no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        accion = (request.data.get("accion") or "confirmar").lower()
        if accion == "rechazar":
            if pago.estado == EstadoPagoTaller.PENDIENTE:
                pago.estado = EstadoPagoTaller.FALLIDO
                pago.save(update_fields=["estado", "updated_at"])
            return Response({"ok": True, "estado": pago.estado}, status=status.HTTP_200_OK)

        if pago.estado == EstadoPagoTaller.PENDIENTE and pago.fecha_expiracion and timezone.now() > pago.fecha_expiracion:
            pago.estado = EstadoPagoTaller.VENCIDO
            pago.save(update_fields=["estado", "updated_at"])
            return Response({"ok": True, "estado": pago.estado, "resultado": "vencido"}, status=status.HTTP_200_OK)

        monto_confirmado = monto_esperado_para_validacion(pago)
        if pago.estado != EstadoPagoTaller.CONFIRMADO:
            pago.estado = EstadoPagoTaller.CONFIRMADO
            pago.monto_pagado = monto_confirmado
            pago.fecha_pago = timezone.now()
            pago.recibido_at = pago.fecha_pago
            pago.save(update_fields=["estado", "monto_pagado", "fecha_pago", "recibido_at", "updated_at"])
        return Response({"ok": True, "estado": pago.estado, "resultado": "confirmado"}, status=status.HTTP_200_OK)

