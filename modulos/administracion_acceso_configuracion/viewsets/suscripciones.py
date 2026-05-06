""" Viewsets para gestionar suscripciones y pagos en Stripe.
FLUJOS DE NEGOCIO IMPLEMENTADOS:
1. CAMBIO DE PLAN (cambiar-plan â†’ crear_payment_intent (accion=cambiar) â†’ confirmar_pago (accion=cambiar))
2. RENOVACIÃ“N (crear_payment_intent (accion=renovar) â†’ confirmar_pago (accion=renovar))
3. CANCELACIÃ“N DE CAMBIO PENDIENTE (cancelar-cambio)
4. OBTENER ESTADO ACTUAL (actual)
ENDPOINTS DISPONIBLES:
- GET /api/{empresa_slug}/suscripciones/actual/ 
- POST /api/{empresa_slug}/suscripciones/cambiar-plan/
- POST /api/{empresa_slug}/suscripciones/cancelar-cambio/
- POST /api/{empresa_slug}/suscripciones/crear_payment_intent/
- POST /api/{empresa_slug}/suscripciones/confirmar_pago/
- POST /api/{empresa_slug}/suscripciones/renovar/ (DESHABILITADO). """

from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import transaction
from django.db.utils import IntegrityError
from django.conf import settings
from datetime import timedelta
import stripe
import os
import logging

from modulos.administracion_acceso_configuracion.models import Suscripcion, Plan, Pago, Empresa, EstadoSuscripcion
from modulos.administracion_acceso_configuracion.serializers.suscripciones import (
    SuscripcionSerializer,
    PlanSerializer,
    PagoSerializer
)
from nucleo.permisos import IsCompanyAdmin
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    registrar_evento_on_commit,
    AccionAuditoria,
)
# Configurar Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', 'sk_test_default')
logger = logging.getLogger(__name__)

class SuscripcionViewSet(viewsets.ViewSet):
    """ ViewSet para gestionar suscripciones de empresas. FLUJO:
    1. CAMBIAR PLAN:
       - POST cambiar-plan â†’ programa plan_pendiente
       - POST crear_payment_intent (accion='cambiar') â†’ crea intent con monto calculado
       - Pago completado en Stripe
       - POST confirmar_pago (accion='cambiar') â†’ registra pago, vincula a suscripciÃ³n
       - Apply automÃ¡tico cuando llegue fecha_aplicacion_plan_pendiente  
    2. RENOVAR:
       - POST crear_payment_intent (accion='renovar') â†’ crea intent con monto del plan actual
       - Pago completado en Stripe
       - POST confirmar_pago (accion='renovar') â†’ extiende perÃ­odo actual
    3. CANCELAR:
       - POST cancelar-cambio â†’ limpia plan_pendiente y pago asociado
    ENDPOINTS:
    - GET /api/{empresa_slug}/suscripciones/actual/ 
    - POST /api/{empresa_slug}/suscripciones/cambiar-plan/
    - POST /api/{empresa_slug}/suscripciones/cancelar-cambio/
    - POST /api/{empresa_slug}/suscripciones/crear_payment_intent/
    - POST /api/{empresa_slug}/suscripciones/confirmar_pago/ """
    permission_classes = [IsAuthenticated, IsCompanyAdmin]
    
    def get_empresa(self, request):
        """ Obtener la empresa del request con validaciÃ³n explÃ­cita de pertenencia.
        El usuario debe pertenecer a la empresa resuelta. """
        # Usar request.resolver_match.kwargs para acciones
        # o request.tenant que el middleware proporciona
        if hasattr(request, 'tenant') and request.tenant:
            empresa = request.tenant
        else:
            # Fallback: obtener del resolver
            empresa_slug = request.resolver_match.kwargs.get('empresa_slug')
            if empresa_slug:
                try:
                    empresa = Empresa.objects.get(slug=empresa_slug)
                except Empresa.DoesNotExist:
                    return None
            else:
                return None
        # ValidaciÃ³n explÃ­cita: el usuario debe pertenecer a esta empresa
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return None
        
        if request.user.empresa_id != empresa.id:
            return None
        return empresa
    
    def _tiene_pago_confirmado_para_plan_pendiente(self, suscripcion):
        """ Verifica si existe un Pago confirmado para el plan_pendiente actual.
        REGLA DE NEGOCIO:
        - Si el usuario ya pagÃ³ por un cambio pendiente, NO se puede reemplazar silenciosamente
        - El usuario debe cancelar/rechazar el cambio pendiente antes de elegir otro plan
        Returns: Tupla (tiene_pago_confirmado: bool, pago: Pago|None, plan_nombre: str|None) """
        if not suscripcion.pago_plan_pendiente:
            return False, None, None
        pago = suscripcion.pago_plan_pendiente
        # Verificar si el pago estÃ¡ en estado COMPLETADO
        if pago.estado == 'COMPLETADO':
            plan_nombre = suscripcion.plan_pendiente.nombre if suscripcion.plan_pendiente else "desconocido"
            return True, pago, plan_nombre
        return False, None, None
    
    def _aplicar_plan_pendiente_si_corresponde(self, suscripcion, empresa):
        """ Verifica si existe un plan pendiente y su fecha de aplicaciÃ³n ya llegÃ³.
        Si es asÃ­, lo aplica automÃ¡ticamente dentro de una transacciÃ³n.
        - Ejemplo: fin = 2025-03-31 23:59:59, inicio_siguiente = 2025-04-01 00:00:00
        Args:
            suscripcion: Objeto Suscripcion
            empresa: Objeto Empresa
        Returns:
            True si se aplicÃ³ el plan pendiente, False si no hay pendiente o fecha no llegÃ³ """
        if not suscripcion.plan_pendiente or not suscripcion.fecha_aplicacion_plan_pendiente:
            return False
        ahora = timezone.now()
        # Verificar si la fecha de aplicaciÃ³n ya llegÃ³
        if ahora >= suscripcion.fecha_aplicacion_plan_pendiente:
            try:
                with transaction.atomic():
                    plan_nuevo = suscripcion.plan_pendiente
                    inicio_nuevo = suscripcion.fecha_aplicacion_plan_pendiente
                    fin_nuevo = inicio_nuevo + timedelta(days=plan_nuevo.duracion_dias) - timedelta(seconds=1)
                    suscripcion.plan = plan_nuevo
                    suscripcion.inicio = inicio_nuevo
                    suscripcion.fin = fin_nuevo
                    suscripcion.estado = EstadoSuscripcion.ACTIVA
                    suscripcion.plan_pendiente = None
                    suscripcion.fecha_aplicacion_plan_pendiente = None
                    suscripcion.pago_plan_pendiente = None  # Limpiar referencia de pago
                    suscripcion.save()
                    empresa.suscripcion_hasta = fin_nuevo
                    empresa.save()
                    # AuditorÃ­a: plan pendiente aplicado (diferido con on_commit)
                    registrar_evento_on_commit(
                        empresa=empresa,
                        accion=AccionAuditoria.SUSCRIPCION_PLAN_PENDIENTE_APLICADO,
                        usuario=None,  # AplicaciÃ³n automÃ¡tica, no hay usuario que lo dispare
                        entidad_tipo="Suscripcion",
                        entidad_id=suscripcion.id,
                        descripcion=f"Plan pendiente aplicado automÃ¡ticamente: {plan_nuevo.nombre}",
                        metadata={
                            "plan_anterior": suscripcion.plan.nombre if suscripcion.plan else None,
                            "plan_nuevo": plan_nuevo.nombre,
                            "fecha_aplicacion": inicio_nuevo.isoformat(),
                        }
                    )
                    return True
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.error(
                    f"Error al aplicar plan pendiente para suscripciÃ³n {suscripcion.id}: {str(e)}",
                    exc_info=True
                )
                return False
        return False
    
    @action(detail=False, methods=['get'], url_path='actual')
    def obtener_suscripcion_actual(self, request, empresa_slug=None):
        """ Obtener la suscripciÃ³n activa de la empresa.
        POST /api/{empresa_slug}/suscripciones/actual/
        Retorna:
        {
            "id": "uuid",
            "empresa": "uuid",
            "plan": { "id", "nombre", "precio_centavos", ... },
            "inicio": "2025-03-01T00:00:00Z",
            "fin": "2025-03-31T23:59:59Z",
            "estado": "ACTIVA",
            "plan_pendiente": { ... } si existe cambio programado,
            "fecha_aplicacion_plan_pendiente": "2025-04-01T00:00:00Z" si existe,
            "pago_plan_pendiente": { ... } si hay pago confirmado para cambio,
            ...
        }
        Responde 404 si:
        - Empresa no existe o Empresa no tiene suscripciÃ³n activa """
        empresa = self.get_empresa(request)
        if not empresa:
            return Response(
                {'error': 'Empresa no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            suscripcion = empresa.suscripcion
            # Aplicar plan pendiente si su fecha ya llegÃ³
            self._aplicar_plan_pendiente_si_corresponde(suscripcion, empresa)
            serializer = SuscripcionSerializer(suscripcion)
            return Response(serializer.data)
        except Suscripcion.DoesNotExist:
            return Response(
                {'error': 'Sin suscripciÃ³n activa'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=False, methods=['post'], url_path='cambiar-plan')
    def cambiar_plan(self, request, empresa_slug=None):
        """ Programar cambio de plan para despuÃ©s del perÃ­odo actual de cobertura.
        POST /api/{empresa_slug}/suscripciones/cambiar-plan/
        Body:
        {
            "planId": "uuid-del-plan-nuevo"
        }
        Responde 400 si:
        El plan es el mismo que el actual o Ya hay pago confirmado para otro cambio pendiente
        Responde 404 si:
        Plan no existe o no estÃ¡ activo o Empresa no tiene suscripciÃ³n. """
        empresa = self.get_empresa(request)
        if not empresa:
            return Response(
                {'error': 'Empresa no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        plan_id = request.data.get('planId')
        if not plan_id:
            return Response(
                {'error': 'planId requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            nuevo_plan = Plan.objects.get(id=plan_id, activo=True)
        except Plan.DoesNotExist:
            return Response(
                {'error': 'Plan no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            with transaction.atomic():
                suscripcion = empresa.suscripcion
                plan_actual = suscripcion.plan
                # Si es el mismo plan: Error (debe usar renovaciÃ³n)
                if nuevo_plan.id == plan_actual.id:
                    return Response(
                        {'error': 'Para renovar el plan actual, usa la opciÃ³n de renovaciÃ³n con pago.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Verificar si hay pago CONFIRMADO para otro plan pendiente
                tiene_pago_confirmado, pago_confirmado, plan_pendiente_nombre = \
                    self._tiene_pago_confirmado_para_plan_pendiente(suscripcion)
                if tiene_pago_confirmado:
                    return Response(
                        {
                            'error': f'No puedes cambiar de plan. Ya has confirmado pago para cambiar a {plan_pendiente_nombre}. '
                                    f'Espera a que se aplique automÃ¡ticamente o contacta soporte para cancelarlo.',
                            'codigo_error': 'PAGO_CONFIRMADO_PENDIENTE',
                            'pago_id': str(pago_confirmado.id),
                            'plan_pendiente': plan_pendiente_nombre
                        },
                        status=status.HTTP_409_CONFLICT
                    )
                # Programar cambio: reemplazar plan_pendiente si existe, o crear nuevo
                fecha_aplicacion = suscripcion.fin + timedelta(seconds=1)
                suscripcion.plan_pendiente = nuevo_plan
                suscripcion.fecha_aplicacion_plan_pendiente = fecha_aplicacion
                # Si reemplazamos plan_pendiente, invalidar pago anterior
                suscripcion.pago_plan_pendiente = None
                suscripcion.save()
                # AuditorÃ­a: cambio de plan programado
                registrar_evento_desde_request(
                    request,
                    empresa=empresa,
                    accion=AccionAuditoria.SUSCRIPCION_CAMBIO_PROGRAMADO,
                    usuario=request.user,
                    entidad_tipo="Suscripcion",
                    entidad_id=suscripcion.id,
                    descripcion=f"Cambio de plan programado: {plan_actual.nombre} â†’ {nuevo_plan.nombre} para el {fecha_aplicacion.isoformat()}",
                    metadata={
                        "plan_actual": plan_actual.nombre,
                        "plan_pendiente": nuevo_plan.nombre,
                        "fecha_aplicacion_plan_pendiente": fecha_aplicacion.isoformat(),
                    }
                )
                serializer = SuscripcionSerializer(suscripcion)
                return Response({
                    'success': True,
                    'mensaje': f'Cambio a plan {nuevo_plan.nombre} programado para {fecha_aplicacion.isoformat()}',
                    'suscripcion': serializer.data
                })
        except Suscripcion.DoesNotExist:
            return Response(
                {'error': 'Empresa sin suscripciÃ³n activa'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'], url_path='cancelar-cambio')
    def cancelar_cambio_pendiente(self, request, empresa_slug=None):
        """ Cancelar un cambio de plan pendiente y sus pagos asociados.
        POST /api/{empresa_slug}/suscripciones/cancelar-cambio/"""
        empresa = self.get_empresa(request)
        if not empresa:
            return Response(
                {'error': 'Empresa no encontrada o sin pertenencia'},
                status=status.HTTP_404_NOT_FOUND
            )
        try:
            with transaction.atomic():
                suscripcion = empresa.suscripcion
                # Verificar que hay un cambio pendiente
                if not suscripcion.plan_pendiente:
                    return Response(
                        {
                            'error': 'No hay cambio de plan pendiente que cancelar.',
                            'codigo_error': 'SIN_CAMBIO_PENDIENTE',
                            'suscripcion': SuscripcionSerializer(suscripcion).data
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Limpiar campos de cambio pendiente
                plan_cancelado = suscripcion.plan_pendiente.nombre
                plan_cancelado_id = suscripcion.plan_pendiente.id
                fecha_aplicacion = suscripcion.fecha_aplicacion_plan_pendiente
                pago_id = suscripcion.pago_plan_pendiente.id if suscripcion.pago_plan_pendiente else None
                suscripcion.plan_pendiente = None
                suscripcion.fecha_aplicacion_plan_pendiente = None
                suscripcion.pago_plan_pendiente = None  # Desvincula pago pero no lo elimina
                suscripcion.save()
                # AuditorÃ­a: cambio de plan cancelado
                registrar_evento_desde_request(
                    request,
                    empresa=request.tenant,
                    accion=AccionAuditoria.SUSCRIPCION_CAMBIO_CANCELADO,
                    usuario=request.user,
                    entidad_tipo="Suscripcion",
                    entidad_id=suscripcion.id,
                    descripcion=f"Cambio de plan cancelado: {plan_cancelado}",
                    metadata={
                        "plan_pendiente_cancelado": plan_cancelado,
                        "plan_pendiente_id": str(plan_cancelado_id),
                        "fecha_aplicacion_cancelada": fecha_aplicacion.isoformat() if fecha_aplicacion else None,
                        "pago_plan_pendiente_id": str(pago_id) if pago_id else None,
                    }
                )
                serializer = SuscripcionSerializer(suscripcion)
                return Response({
                    'success': True,
                    'mensaje': f'Cambio a {plan_cancelado} cancelado exitosamente',
                    'suscripcion': serializer.data
                })
        except Suscripcion.DoesNotExist:
            return Response(
                {'error': 'Empresa sin suscripciÃ³n activa'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'], url_path='renovar')
    def renovar_suscripcion(self, request, empresa_slug=None):
        """ DESHABILITADO: La renovaciÃ³n debe pasar por pago (crear_payment_intent + confirmar_pago).
        Flujo correcto:
        1. POST /api/{empresa_slug}/suscripciones/crear_payment_intent/
           con accion='renovar'
        2. Frontend procesa pago con Stripe
        3. POST /api/{empresa_slug}/suscripciones/confirmar_pago/
           con accion='renovar'
        Esta ruta sigue existiendo pero retorna error explÃ­cito para claridad histÃ³rica. """
        return Response(
            {
                'error': 'La renovaciÃ³n de suscripciÃ³n debe hacerse a travÃ©s del flujo de pago. '
                        'Usa crear_payment_intent (accion=renovar) seguido de confirmar_pago.',
                'codigo_error': 'RENOVACION_REQUIERE_PAGO',
                'flujo_correcto': {
                    '1_crear_intent': 'POST /api/{empresa_slug}/suscripciones/crear_payment_intent/',
                    '1_body': {'planId': 'uuid-del-plan', 'accion': 'renovar'},
                    '2_procesar_pago': 'Completar pago en Stripe',
                    '3_confirmar_pago': 'POST /api/{empresa_slug}/suscripciones/confirmar_pago/',
                    '3_body': {'paymentIntentId': 'pi_...', 'planId': 'uuid', 'accion': 'renovar'}
                }
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=False, methods=['post'], url_path='crear_payment_intent')
    def crear_payment_intent(self, request, empresa_slug=None):
        """ Crear un Payment Intent en Stripe para cambio o renovaciÃ³n de suscripciÃ³n.
        VALIDACIÃ“N POR ACCIÃ“N:
        - accion='cambiar': Valida que hay suscripciÃ³n, plan_pendiente programado, plan coherente
        - accion='renovar': Valida que NO hay plan_pendiente, plan coherente
        - acciÃ³n invÃ¡lida: Error 400
        POST /api/{empresa_slug}/suscripciones/crear_payment_intent/"""
        empresa = self.get_empresa(request)
        if not empresa:
            return Response(
                {'error': 'Empresa no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        logger = logging.getLogger(__name__)
        try:
            plan_id = request.data.get('planId')
            accion = request.data.get('accion')
            # Validar parÃ¡metros bÃ¡sicos
            if not plan_id or not accion:
                return Response(
                    {'error': 'planId y accion son requeridos'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Validar acciÃ³n
            if accion not in ['cambiar', 'renovar']:
                return Response(
                    {'error': f'accion invÃ¡lida: "{accion}". Debe ser "cambiar" o "renovar"'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Obtener suscripciÃ³n y plan
            try:
                suscripcion = empresa.suscripcion
            except Suscripcion.DoesNotExist:
                return Response(
                    {'error': 'Empresa sin suscripciÃ³n activa'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Obtener plan
            try:
                plan = Plan.objects.get(id=plan_id, activo=True)
            except Plan.DoesNotExist:
                return Response(
                    {'error': 'Plan no encontrado o no activo'},
                    status=status.HTTP_404_NOT_FOUND
                )
            # VALIDACIÃ“N POR ACCIÃ“N
            if accion == 'cambiar':
                # Caso 1: Cambio de plan
                # Validar que el cambio estÃ© programado correctamente
                if not suscripcion.plan_pendiente or suscripcion.plan_pendiente.id != plan.id:
                    return Response(
                        {
                            'error': 'Plan no estÃ¡ programado para cambio. '
                                    'Llama primero a cambiar-plan para programar el cambio.',
                            'codigo_error': 'CAMBIO_NO_PROGRAMADO'
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Validar que no sea el plan actual (cambio debe ser a otro plan)
                if plan.id == suscripcion.plan.id:
                    return Response(
                        {
                            'error': 'El plan programado no puede ser el mismo que el actual. '
                                    'Para renovar el plan actual, usa accion=renovar.',
                            'codigo_error': 'CAMBIO_A_MISMO_PLAN'
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                descripcion = f"Cambio a plan {plan.nombre}"
            elif accion == 'renovar':
                # Caso 2: RenovaciÃ³n
                # Validar que NO haya plan_pendiente (no se puede renovar con cambio programado)
                if suscripcion.plan_pendiente:
                    return Response(
                        {
                            'error': 'No puedes renovar con un cambio de plan programado. '
                                    'Cancela primero el cambio pendiente.',
                            'codigo_error': 'RENOVACION_CON_CAMBIO_PENDIENTE'
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # En renovaciÃ³n, el plan DEBE ser el plan actual
                if plan.id != suscripcion.plan.id:
                    return Response(
                        {
                            'error': 'En renovaciÃ³n, el plan DEBE ser el plan actual. '
                                    'Si deseas cambiar de plan, usa accion=cambiar.',
                            'codigo_error': 'RENOVACION_PLAN_INCORRECTO'
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                descripcion = f"RenovaciÃ³n de plan {plan.nombre}"
            # Calcular monto SIEMPRE desde plan.precio_centavos (nunca del frontend)
            monto = plan.precio_centavos
            if monto <= 0:
                return Response(
                    {
                        'error': 'El plan tiene precio cero o invÃ¡lido. Contacta soporte.',
                        'codigo_error': 'PLAN_PRECIO_INVALIDO'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            # En DESARROLLO: simular Stripe sin llamar a la API
            if settings.DEBUG:
                payment_intent_id = f"pi_dev_{os.urandom(12).hex()}"
                client_secret = f"pi_dev_{os.urandom(24).hex()}_secret_{os.urandom(12).hex()}"
                return Response({
                    'id': payment_intent_id,
                    'client_secret': client_secret,
                    'status': 'requires_payment_method',
                    'amount': monto,
                    'currency': 'usd',
                    'plan_nombre': plan.nombre,
                    'accion': accion,
                }, status=status.HTTP_200_OK)
            # En PRODUCCIÃ“N: usar Stripe real
            customer_id = empresa.stripe_customer_id
            if not customer_id:
                # Crear nuevo customer en Stripe
                try:
                    customer = stripe.Customer.create(
                        email=request.user.email,
                        name=f"{request.user.nombres} {request.user.apellidos}",
                        metadata={
                            'empresa_slug': empresa.slug,
                            'empresa_nombre': empresa.nombre,
                        }
                    )
                    customer_id = customer.id
                    # Guardar el ID del customer en la empresa (persistido)
                    empresa.stripe_customer_id = customer_id
                    empresa.save()
                except stripe.error.StripeError as e:
                    logger.error(f"Error creando customer Stripe para {empresa.slug}: {str(e)}")
                    return Response(
                        {'error': f'Error creando cliente Stripe: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            # Crear Payment Intent con Stripe
            try:
                intent = stripe.PaymentIntent.create(
                    amount=monto,
                    currency='usd',
                    customer=customer_id,
                    description=descripcion,
                    metadata={
                        'empresa_slug': empresa.slug,
                        'empresa_id': str(empresa.id),
                        'plan_id': plan_id,
                        'plan_nombre': plan.nombre,
                        'accion': accion,
                        'usuario_email': request.user.email,
                    }
                )
            except stripe.error.StripeError as e:
                logger.error(f"Error creando PaymentIntent para {empresa.slug}, accion={accion}: {str(e)}")
                return Response(
                    {'error': f'Error de Stripe: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            return Response({
                'id': intent.id,
                'client_secret': intent.client_secret,
                'status': intent.status,
                'amount': intent.amount,
                'currency': intent.currency,
                'plan_nombre': plan.nombre,
                'accion': accion,
            })
        except Plan.DoesNotExist:
            return Response(
                {'error': 'Plan no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error inesperado en crear_payment_intent: {str(e)}", exc_info=True)
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'], url_path='confirmar_pago')
    def confirmar_pago(self, request, empresa_slug=None):
        """ Confirmar pago en Stripe y materializar cambio o renovaciÃ³n.
        En DEBUG mode, acepta cualquier paymentIntentId que comience con 'pi_dev_'
        POST /api/{empresa_slug}/suscripciones/confirmar_pago/
        Body:
        {
            "paymentIntentId": "pi_...",
            "planId": "uuid-del-plan",
            "accion": "cambiar" o "renovar"
        }"""
        empresa = self.get_empresa(request)
        if not empresa:
            return Response(
                {'error': 'Empresa no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        logger = logging.getLogger(__name__)
        try:
            payment_intent_id = request.data.get('paymentIntentId')
            plan_id = request.data.get('planId')
            accion = request.data.get('accion')
            if not all([payment_intent_id, plan_id, accion]):
                return Response(
                    {'error': 'ParÃ¡metros requeridos faltantes'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Validar el estado del Payment Intent
            if settings.DEBUG and payment_intent_id.startswith('pi_dev_'):
                # En DEBUG: aceptar automÃ¡ticamente
                payment_intent_status = 'succeeded'
            else:
                # En PRODUCCIÃ“N: validar en Stripe
                intent = stripe.PaymentIntent.retrieve(payment_intent_id)
                payment_intent_status = intent.status
            if payment_intent_status != 'succeeded':
                return Response(
                    {'error': f'Pago no completado. Estado: {payment_intent_status}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Obtener el plan
            plan = Plan.objects.get(id=plan_id, activo=True)
            # Validar acciÃ³n (ANTES de transacciÃ³n)
            if accion not in ['cambiar', 'renovar']:
                return Response(
                    {'error': f'accion invÃ¡lida: "{accion}". Debe ser "cambiar" o "renovar"'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            with transaction.atomic():
                suscripcion = empresa.suscripcion
                if accion == 'cambiar':
                    # Validar que exista plan_pendiente programado
                    if not suscripcion.plan_pendiente or suscripcion.plan_pendiente.id != plan.id:
                        return Response(
                            {'error': 'Plan no estÃ¡ programado para cambio. Programa primero via cambiar_plan.'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    # NO permitimos otro payment_intent_id. Solo un pago confirmado por cambio.
                    if suscripcion.pago_plan_pendiente and suscripcion.pago_plan_pendiente.estado == 'COMPLETADO':
                        # Si es el mismo payment_intent_id, es idempotencia (proceder normalmente)
                        if suscripcion.pago_plan_pendiente.stripe_payment_intent_id != payment_intent_id:
                            return Response(
                                {
                                    'error': 'Ya existe un pago confirmado para este cambio pendiente. '
                                            'No se permite mÃºltiples pagos para el mismo cambio. '
                                            'Usa el mismo payment_intent_id o cancela el cambio pendiente.',
                                    'codigo_error': 'PAGO_DUPLICADO_PARA_CAMBIO',
                                    'payment_intent_existente': suscripcion.pago_plan_pendiente.stripe_payment_intent_id
                                },
                                status=status.HTTP_409_CONFLICT
                            )
                    # Crear o reutilizar Pago para cambio
                    pago_para_usar = None
                    pago_fue_creado = False
                    try:
                        pago_para_usar, pago_fue_creado = Pago.objects.get_or_create(
                            stripe_payment_intent_id=payment_intent_id,
                            defaults={
                                'empresa': empresa,
                                'plan': plan,
                                'amount_centavos': plan.precio_centavos,
                                'moneda': 'USD',
                                'empresa_slug': empresa.slug,
                                'empresa_nombre': empresa.nombre,
                                'usuario_email': request.user.email,
                                'usuario_nombres': request.user.nombres,
                                'usuario_apellidos': request.user.apellidos,
                                'stripe_session_id': None,
                                'estado': 'COMPLETADO',
                                'processed_at': timezone.now()
                            }
                        )
                    except IntegrityError:
                        try:
                            pago_para_usar = Pago.objects.get(
                                stripe_payment_intent_id=payment_intent_id
                            )
                            pago_fue_creado = False
                        except Pago.DoesNotExist:
                            logger.error(
                                f"IntegrityError pero Pago no recuperable (cambio) {payment_intent_id} empresa {empresa.id}",
                                exc_info=True
                            )
                            return Response(
                                {'error': 'Error de persistencia. Reintenta.', 'codigo_error': 'PAGO_INTEGRIDAD_IRRECUPERABLE'},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR
                            )
                    # Validar contexto
                    if not pago_fue_creado:
                        if pago_para_usar.empresa_id != empresa.id:
                            return Response(
                                {'error': 'Pago pertenece a otra empresa.', 'codigo_error': 'PAGO_CONTEXTO_INVALIDO_EMPRESA'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        if pago_para_usar.plan_id != plan.id:
                            return Response(
                                {'error': f'Pago es para otro plan ({pago_para_usar.plan.nombre}).', 'codigo_error': 'PAGO_PLAN_MISMATCH'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        if pago_para_usar.estado not in ['COMPLETADO', 'PENDIENTE']:
                            return Response(
                                {'error': f'Pago en estado {pago_para_usar.estado}.', 'codigo_error': 'PAGO_ESTADO_INVALIDO'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        if pago_para_usar.estado != 'COMPLETADO':
                            pago_para_usar.estado = 'COMPLETADO'
                            pago_para_usar.processed_at = timezone.now()
                            pago_para_usar.save()
                    # Vincular pago a suscripciÃ³n
                    suscripcion.pago_plan_pendiente = pago_para_usar
                    suscripcion.referencia_pago = payment_intent_id
                    suscripcion.save()
                    # AuditorÃ­a: pago confirmado para cambio (diferido con on_commit)
                    registrar_evento_on_commit(
                        empresa=empresa,
                        accion=AccionAuditoria.SUSCRIPCION_PAGO_CONFIRMADO_CAMBIO,
                        usuario=request.user,
                        entidad_tipo="Suscripcion",
                        entidad_id=suscripcion.id,
                        descripcion=f"Pago confirmado para cambio a plan {plan.nombre}",
                        metadata={
                            "plan_pendiente": plan.nombre,
                            "fecha_aplicacion_plan_pendiente": suscripcion.fecha_aplicacion_plan_pendiente.isoformat() if suscripcion.fecha_aplicacion_plan_pendiente else None,
                            "payment_intent_id": payment_intent_id,
                            "pago_id": str(pago_para_usar.id),
                        }
                    )
                elif accion == 'renovar':
                    # Validar que no haya plan_pendiente programado
                    if suscripcion.plan_pendiente:
                        return Response(
                            {'error': 'No puedes renovar con cambio pendiente. Cancela primero el cambio.'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    # IDEMPOTENCIA: Crear o reutilizar Pago para renovaciÃ³n
                    pago_para_usar = None
                    pago_fue_creado = False
                    try:
                        pago_para_usar, pago_fue_creado = Pago.objects.get_or_create(
                            stripe_payment_intent_id=payment_intent_id,
                            defaults={
                                'empresa': empresa,
                                'plan': plan,
                                'amount_centavos': plan.precio_centavos,
                                'moneda': 'USD',
                                'empresa_slug': empresa.slug,
                                'empresa_nombre': empresa.nombre,
                                'usuario_email': request.user.email,
                                'usuario_nombres': request.user.nombres,
                                'usuario_apellidos': request.user.apellidos,
                                'stripe_session_id': None,
                                'estado': 'COMPLETADO',
                                'processed_at': timezone.now()
                            }
                        )
                    except IntegrityError:
                        try:
                            pago_para_usar = Pago.objects.get(
                                stripe_payment_intent_id=payment_intent_id
                            )
                            pago_fue_creado = False
                        except Pago.DoesNotExist:
                            logger.error(
                                f"IntegrityError pero Pago no recuperable (renovar) {payment_intent_id} empresa {empresa.id}",
                                exc_info=True
                            )
                            return Response(
                                {'error': 'Error de persistencia. Reintenta.', 'codigo_error': 'PAGO_INTEGRIDAD_IRRECUPERABLE'},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR
                            )
                    # Validar contexto
                    if not pago_fue_creado:
                        if pago_para_usar.empresa_id != empresa.id:
                            return Response(
                                {'error': 'Pago pertenece a otra empresa.', 'codigo_error': 'PAGO_CONTEXTO_INVALIDO_EMPRESA'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        if pago_para_usar.plan_id != plan.id:
                            return Response(
                                {'error': f'Pago es para otro plan ({pago_para_usar.plan.nombre}).', 'codigo_error': 'PAGO_PLAN_MISMATCH'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        if pago_para_usar.estado not in ['COMPLETADO', 'PENDIENTE']:
                            return Response(
                                {'error': f'Pago en estado {pago_para_usar.estado}.', 'codigo_error': 'PAGO_ESTADO_INVALIDO'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        if pago_para_usar.estado != 'COMPLETADO':
                            pago_para_usar.estado = 'COMPLETADO'
                            pago_para_usar.processed_at = timezone.now()
                            pago_para_usar.save()
                    # Renovar: extender perÃ­odo actual
                    fecha_inicio = suscripcion.fin + timedelta(seconds=1)
                    fecha_fin = fecha_inicio + timedelta(days=plan.duracion_dias) - timedelta(seconds=1)
                    suscripcion.plan = plan
                    suscripcion.inicio = fecha_inicio
                    suscripcion.fin = fecha_fin
                    suscripcion.estado = EstadoSuscripcion.ACTIVA
                    suscripcion.plan_pendiente = None
                    suscripcion.fecha_aplicacion_plan_pendiente = None
                    suscripcion.pago_plan_pendiente = None
                    suscripcion.referencia_pago = payment_intent_id
                    suscripcion.save()
                    empresa.suscripcion_hasta = fecha_fin
                    empresa.save()
                    # AuditorÃ­a: suscripciÃ³n renovada (diferido con on_commit)
                    registrar_evento_on_commit(
                        empresa=empresa,
                        accion=AccionAuditoria.SUSCRIPCION_RENOVADA,
                        usuario=request.user,
                        entidad_tipo="Suscripcion",
                        entidad_id=suscripcion.id,
                        descripcion=f"SuscripciÃ³n renovada: plan {plan.nombre}",
                        metadata={
                            "plan": plan.nombre,
                            "fecha_inicio_nueva": fecha_inicio.isoformat(),
                            "fecha_fin_nueva": fecha_fin.isoformat(),
                            "payment_intent_id": payment_intent_id,
                            "pago_id": str(pago_para_usar.id),
                        }
                    )
                serializer = SuscripcionSerializer(suscripcion)
                return Response({
                    'success': True,
                    'mensaje': 'Pago procesado exitosamente',
                    'nueva_fecha_fin': suscripcion.fin.isoformat(),
                    'suscripcion': serializer.data
                })
        except Plan.DoesNotExist:
            return Response(
                {'error': 'Plan no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {'error': f'Error de Stripe: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Suscripcion.DoesNotExist:
            return Response(
                {'error': 'Empresa sin suscripciÃ³n activa'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
