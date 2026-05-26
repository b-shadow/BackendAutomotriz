from decimal import Decimal
import uuid
from urllib.parse import quote

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.conf import settings
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
        return {"ok": True, "status": status.HTTP_200_OK, "body": {"ok": True, "estado": pago.estado}}

    if estado_norm in [EstadoPagoTaller.FALLIDO, EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO, EstadoPagoTaller.PROCESANDO]:
        pago.estado = estado_norm
        pago.save(update_fields=["estado", "updated_at"])
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
        return Response(self._serialize(compra))


class VentaMostradorViewSet(viewsets.ModelViewSet):
    serializer_class = VentaMostradorSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionAdministrativa]

    def get_queryset(self):
        return VentaMostrador.objects.filter(empresa=self.request.tenant).prefetch_related("detalles").order_by("-created_at")

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
        return Response(VentaMostradorSerializer(venta).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="confirmar")
    @transaction.atomic
    def confirmar(self, request, pk=None, **kwargs):
        venta = self.get_object()
        if venta.estado == EstadoVentaMostrador.CONFIRMADA:
            return Response({"error": "La venta ya esta confirmada."}, status=status.HTTP_400_BAD_REQUEST)
        if venta.estado == EstadoVentaMostrador.ANULADA:
            return Response({"error": "La venta esta anulada."}, status=status.HTTP_400_BAD_REQUEST)

        for det in venta.detalles.select_related("item_inventario"):
            item = det.item_inventario
            if not item:
                continue
            if item.stock_actual < det.cantidad:
                return Response({"error": f"Stock insuficiente para {item.nombre}."}, status=status.HTTP_400_BAD_REQUEST)
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
        return Response(VentaMostradorSerializer(venta).data)


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
                elif estado_norm in [EstadoPagoTaller.FALLIDO, EstadoPagoTaller.CANCELADO, EstadoPagoTaller.VENCIDO]:
                    pago.estado = estado_norm
                    pago.respuesta_proveedor_raw = estado_proveedor.get("raw")
                    pago.save(update_fields=["estado", "respuesta_proveedor_raw", "updated_at"])
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
            return Response({"ok": True, "estado": pago.estado}, status=status.HTTP_200_OK)
        resultado = self._aplicar_confirmacion_simulada(pago)
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

        caja = CajaUsuario.objects.filter(empresa=request.tenant, administrativo=request.user, activa=True).first()
        if caja:
            MovimientoCaja.objects.create(
                empresa=request.tenant,
                caja=caja,
                tipo=TipoMovimientoCaja.INGRESO,
                concepto=f"Pago recibido {pago.id}",
                monto=pago.monto_total,
                pago_taller=pago,
                registrado_por=request.user,
            )

        return Response(PagoTallerSerializer(pago).data)


class FacturaViewSet(viewsets.ModelViewSet):
    serializer_class = FacturaSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarCajaPagos]

    def get_queryset(self):
        return Factura.objects.filter(empresa=self.request.tenant).order_by("-created_at")

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
        factura = Factura.objects.create(
            empresa=request.tenant,
            pago_taller=pago,
            numero=numero,
            nit_razon_social=request.data.get("nit_razon_social", ""),
            total=pago.monto_total,
            archivo_pdf_url=request.data.get("archivo_pdf_url", ""),
        )
        pago.estado = EstadoPagoTaller.FACTURADO
        pago.save(update_fields=["estado", "updated_at"])
        return Response(FacturaSerializer(factura).data, status=status.HTTP_201_CREATED)


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

        movs = MovimientoCaja.objects.filter(empresa=request.tenant, caja=caja).order_by("-created_at")[:50]
        ingresos = movs.filter(tipo=TipoMovimientoCaja.INGRESO).aggregate(total=Sum("monto")).get("total") or Decimal("0")
        egresos = movs.filter(tipo=TipoMovimientoCaja.EGRESO).aggregate(total=Sum("monto")).get("total") or Decimal("0")
        ajustes = movs.filter(tipo=TipoMovimientoCaja.AJUSTE).aggregate(total=Sum("monto")).get("total") or Decimal("0")
        saldo = ingresos - egresos + ajustes
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
