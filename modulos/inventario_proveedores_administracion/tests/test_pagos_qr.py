from decimal import Decimal

from django.test import SimpleTestCase, override_settings

from modulos.inventario_proveedores_administracion.services.pagos_qr import (
    PagoQRError,
    calcular_monto_cobrado,
    validar_monto_real,
)


class PagosQRRulesTest(SimpleTestCase):
    @override_settings(PAGOS_DIVISOR_PRUEBA=1000, PAGOS_MONTO_REAL_MINIMO=10, PAGOS_MONTO_REAL_MULTIPLO=10)
    def test_calcular_monto_cobrado_prueba_real(self):
        result = calcular_monto_cobrado(Decimal("800.00"), "PRUEBA_REAL")
        self.assertEqual(result, Decimal("0.80"))

    @override_settings(PAGOS_DIVISOR_PRUEBA=1000, PAGOS_MONTO_REAL_MINIMO=10, PAGOS_MONTO_REAL_MULTIPLO=10)
    def test_calcular_monto_cobrado_produccion(self):
        result = calcular_monto_cobrado(Decimal("800.00"), "PRODUCCION")
        self.assertEqual(result, Decimal("800.00"))

    @override_settings(PAGOS_MONTO_REAL_MINIMO=10, PAGOS_MONTO_REAL_MULTIPLO=10)
    def test_monto_real_invalido(self):
        with self.assertRaises(PagoQRError):
            validar_monto_real(Decimal("15.00"))

