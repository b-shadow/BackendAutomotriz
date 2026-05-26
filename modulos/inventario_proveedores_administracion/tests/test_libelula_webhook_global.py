from decimal import Decimal
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from modulos.administracion_acceso_configuracion.models import Empresa
from modulos.inventario_proveedores_administracion.models import (
    EstadoPagoTaller,
    PagoTaller,
    TipoOrigenPagoTaller,
)


@override_settings(
    LIBELULA_BASE_URL="https://api.libelula.test",
    LIBELULA_API_KEY="test_key",
    LIBELULA_API_SECRET="test_secret",
    LIBELULA_CALLBACK_TOKEN="",
)
class LibelulaWebhookGlobalTests(APITestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Empresa Test", slug="empresa-test")
        self.url = "/api/pagos/webhooks/libelula/"

    def _crear_pago(self, **extra):
        defaults = {
            "empresa": self.empresa,
            "tipo_origen": TipoOrigenPagoTaller.CITA,
            "tipo_destino": "PRESUPUESTO",
            "id_destino": "dest-1",
            "estado": EstadoPagoTaller.PENDIENTE,
            "proveedor": "LIBELULA_QR",
            "ambiente": "PRUEBA_REAL",
            "monto_total": Decimal("800.00"),
            "monto_real": Decimal("800.00"),
            "monto_cobrado": Decimal("0.80"),
            "metodo_pago": "QR",
            "moneda": "BOB",
            "referencia": "TEST-PRESUPUESTO-1",
            "referencia_externa": "TEST-PRESUPUESTO-1",
            "codigo_pago": "PAGO-TEST-1",
            "fecha_expiracion": timezone.now() + timedelta(minutes=30),
        }
        defaults.update(extra)
        return PagoTaller.objects.create(**defaults)

    def test_callback_confirma_pago_prueba_real(self):
        pago = self._crear_pago()
        payload = {
            "reference": pago.referencia_externa,
            "status": "paid",
            "amount": "0.80",
            "currency": "BOB",
            "transaction_id": "tx-1",
            "payment_id": "lp-1",
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, EstadoPagoTaller.CONFIRMADO)
        self.assertEqual(pago.monto_pagado, Decimal("0.80"))

    def test_callback_es_idempotente_por_payload_duplicado(self):
        pago = self._crear_pago()
        payload = {
            "reference": pago.referencia_externa,
            "status": "paid",
            "amount": "0.80",
            "currency": "BOB",
        }
        r1 = self.client.post(self.url, data=payload, format="json")
        r2 = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data.get("detail"), "callback duplicado")
        pago.refresh_from_db()
        self.assertEqual(pago.callback_intentos, 1)

    def test_callback_monto_incorrecto_en_produccion(self):
        pago = self._crear_pago(
            ambiente="PRODUCCION",
            monto_cobrado=Decimal("800.00"),
        )
        payload = {
            "reference": pago.referencia_externa,
            "status": "paid",
            "amount": "0.80",
            "currency": "BOB",
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, EstadoPagoTaller.MONTO_INCORRECTO)

    def test_callback_rechaza_pago_vencido(self):
        pago = self._crear_pago(fecha_expiracion=timezone.now() - timedelta(minutes=1))
        payload = {
            "reference": pago.referencia_externa,
            "status": "paid",
            "amount": "0.80",
            "currency": "BOB",
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, EstadoPagoTaller.VENCIDO)

