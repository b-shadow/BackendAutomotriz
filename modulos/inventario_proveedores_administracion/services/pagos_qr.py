from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.conf import settings
from django.utils import timezone

from modulos.inventario_proveedores_administracion.models import EstadoPagoTaller


class PagoQRError(Exception):
    pass


def _to_decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validar_monto_real(monto_real: Decimal) -> None:
    minimo = Decimal(str(getattr(settings, "PAGOS_MONTO_REAL_MINIMO", 10)))
    multiplo = Decimal(str(getattr(settings, "PAGOS_MONTO_REAL_MULTIPLO", 10)))
    if monto_real < minimo:
        raise PagoQRError(f"El monto minimo real es Bs {minimo}.")
    if (monto_real % multiplo) != 0:
        raise PagoQRError(f"El monto real debe ser multiplo de {multiplo}.")


def calcular_monto_cobrado(monto_real: Decimal, ambiente: str) -> Decimal:
    validar_monto_real(monto_real)
    if ambiente == "PRUEBA_REAL":
        divisor = Decimal(str(getattr(settings, "PAGOS_DIVISOR_PRUEBA", 1000)))
        if divisor <= 0:
            raise PagoQRError("PAGOS_DIVISOR_PRUEBA invalido.")
        return (monto_real / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if ambiente == "PRODUCCION":
        return monto_real.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    raise PagoQRError("Ambiente de pagos no soportado.")


def generar_referencia_externa(ambiente: str, tipo_destino: str, id_destino: str) -> str:
    prefijo = "TEST" if ambiente == "PRUEBA_REAL" else "PROD"
    short_id = id_destino.replace("-", "")[:16]
    return f"{prefijo}-{tipo_destino}-{short_id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"


def estado_desde_proveedor(raw_estado: str) -> str:
    s = (raw_estado or "").strip().lower()
    if s in {"paid", "pagado", "confirmado", "success", "succeeded"}:
        return EstadoPagoTaller.CONFIRMADO
    if s in {"failed", "fallido", "error"}:
        return EstadoPagoTaller.FALLIDO
    if s in {"processing", "procesando", "pending_review"}:
        return EstadoPagoTaller.PROCESANDO
    if s in {"cancelled", "canceled", "cancelado"}:
        return EstadoPagoTaller.CANCELADO
    if s in {"expired", "vencido"}:
        return EstadoPagoTaller.VENCIDO
    return EstadoPagoTaller.PENDIENTE


def hash_callback(payload: dict) -> str:
    raw = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class LibelulaResponse:
    id_pago_proveedor: str | None
    id_transaccion_proveedor: str | None
    qr_imagen_url: str | None
    qr_imagen_base64: str | None
    url_pago: str | None
    qr_payload: dict | None
    raw: dict


class LibelulaPaymentClient:
    def __init__(self):
        self.base_url = (getattr(settings, "LIBELULA_BASE_URL", "") or "").rstrip("/")
        self.api_key = getattr(settings, "LIBELULA_API_KEY", "")
        self.api_secret = getattr(settings, "LIBELULA_API_SECRET", "")
        self.timeout = int(getattr(settings, "LIBELULA_TIMEOUT_SECONDS", 20))
        self.create_path = getattr(settings, "LIBELULA_CREATE_PATH", "/payments")
        self.status_path = getattr(settings, "LIBELULA_STATUS_PATH", "/payments/{id}")
        self.callback_token = getattr(settings, "LIBELULA_CALLBACK_TOKEN", "")
        if not self.base_url:
            raise PagoQRError("LIBELULA_BASE_URL no configurada.")
        if not self.api_key:
            raise PagoQRError("LIBELULA_API_KEY no configurada.")

    def _headers(self):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.api_secret:
            headers["X-Api-Secret"] = self.api_secret
        return headers

    def crear_cobro(self, *, monto_cobrado: Decimal, moneda: str, descripcion: str, referencia_externa: str, fecha_expiracion, callback_url: str, return_url: str | None = None):
        payload = {
            "amount": str(monto_cobrado),
            "currency": moneda,
            "description": descripcion,
            "reference": referencia_externa,
            "expires_at": fecha_expiracion.isoformat(),
            "callback_url": callback_url,
        }
        if return_url:
            payload["return_url"] = return_url

        url = f"{self.base_url}{self.create_path}"
        try:
            res = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
            res.raise_for_status()
            raw = res.json() if res.content else {}
        except Exception as exc:
            raise PagoQRError(f"Error creando cobro en Libelula: {exc}") from exc

        data = raw.get("data", raw)
        return LibelulaResponse(
            id_pago_proveedor=data.get("id") or data.get("payment_id") or data.get("debt_id"),
            id_transaccion_proveedor=data.get("transaction_id"),
            qr_imagen_url=data.get("qr_image_url") or data.get("qr_url"),
            qr_imagen_base64=data.get("qr_image_base64") or data.get("qr_base64"),
            url_pago=data.get("payment_url") or data.get("url"),
            qr_payload=data.get("qr_payload") or data.get("qr"),
            raw=raw,
        )

    def consultar_estado(self, id_pago_proveedor: str):
        path = self.status_path.replace("{id}", id_pago_proveedor or "")
        url = f"{self.base_url}{path}"
        try:
            res = requests.get(url, headers=self._headers(), timeout=self.timeout)
            res.raise_for_status()
            raw = res.json() if res.content else {}
        except Exception as exc:
            raise PagoQRError(f"Error consultando estado en Libelula: {exc}") from exc
        data = raw.get("data", raw)
        return {
            "estado_proveedor": data.get("status") or data.get("state"),
            "monto_pagado": data.get("paid_amount") or data.get("amount_paid") or data.get("amount"),
            "moneda": data.get("currency"),
            "id_transaccion_proveedor": data.get("transaction_id"),
            "fecha_pago": data.get("paid_at") or data.get("payment_date"),
            "raw": raw,
        }

    def validar_callback(self, headers) -> bool:
        if not self.callback_token:
            return True
        token = headers.get("X-Libelula-Token") or headers.get("Authorization", "").replace("Bearer ", "")
        return bool(token and token == self.callback_token)


def monto_esperado_para_validacion(pago) -> Decimal:
    if pago.ambiente == "PRUEBA_REAL":
        return _to_decimal(pago.monto_cobrado)
    return _to_decimal(pago.monto_real)

