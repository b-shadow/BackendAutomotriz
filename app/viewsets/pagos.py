"""ViewSet para manejar pagos con Stripe.
Maneja la creación de Payment Intents y confirmación de pagos."""
import stripe
import json
import logging
import os
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.hashers import make_password
from django.db import transaction

from app.models import Pago, Empresa, Usuario, Plan, Rol, Suscripcion
from app.serializers import (
    RegistroEmpresaConPagoSerializer,
    ConfirmarPagoSerializer,
    PaymentIntentResponseSerializer,
)
from app.services.empresa_setup import setup_empresa_nueva
from app.services.auditoria_service import (
    registrar_evento_desde_request,
    registrar_evento_on_commit,
    AccionAuditoria,
)

logger = logging.getLogger(__name__)


class PagoViewSet(viewsets.ViewSet):
    """ ViewSet para manejar pagos y registro de empresas con Stripe.
    Endpoints:
    - POST /api/pagos/crear-pago/ - Crear Payment Intent
    - POST /api/pagos/confirmar-pago/ - Confirmar pago y crear empresa """
    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=["post"])
    def crear_pago(self, request):
        """ Crea un Payment Intent en Stripe para el registro de nueva empresa.
        POST /api/pagos/crear_pago/
        {
            "empresa_nombre": "Mi Empresa",
            "empresa_slug": "mi-empresa",
            "usuario_nombres": "Juan",
            "usuario_apellidos": "Pérez",
            "usuario_email": "juan@empresa.com",
            "usuario_password": "contraseña123",
            "plan_id": "uuid-del-plan",
            "customer_email": "billing@empresa.com"  # Optional
        } """
        serializer = RegistroEmpresaConPagoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            # Validar que el plan exista
            plan = Plan.objects.get(id=serializer.validated_data['plan_id'], activo=True)
        except Plan.DoesNotExist:
            return Response(
                {'error': 'Plan no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        # Email del cliente para Stripe
        customer_email = serializer.validated_data.get(
            'customer_email',
            serializer.validated_data['usuario_email']
        )
        try:
            # En DESARROLLO: simular stripe sin llamar a la API
            if settings.DEBUG:
                # Crear Customer simulado
                customer_id = f"cus_dev_{serializer.validated_data['empresa_slug'][:20]}"
                # Crear Payment Intent simulado
                payment_intent_id = f"pi_dev_{os.urandom(12).hex()}"
                client_secret = f"pi_dev_{os.urandom(24).hex()}_secret_{os.urandom(12).hex()}"  
                logger.info(f"DEBUG MODE: Simulando Stripe para {serializer.validated_data['empresa_slug']}")
            else:
                # En PRODUCCIÓN: usar Stripe real
                # Crear Customer en Stripe
                customer = stripe.Customer.create(
                    email=customer_email,
                    name=serializer.validated_data.get('customer_name'),
                    metadata={
                        'empresa_slug': serializer.validated_data['empresa_slug'],
                        'empresa_nombre': serializer.validated_data['empresa_nombre'],
                    }
                )
                customer_id = customer.id
                # Crear Payment Intent
                payment_intent = stripe.PaymentIntent.create(
                    amount=plan.precio_centavos,  # Ya está en centavos
                    currency=settings.STRIPE_CURRENCY,
                    customer=customer.id,
                    description=f"Suscripción a {plan.nombre} - {serializer.validated_data['empresa_nombre']}",
                    metadata={
                        'empresa_slug': serializer.validated_data['empresa_slug'],
                        'plan_id': str(plan.id),
                        'usuario_email': serializer.validated_data['usuario_email'],
                    }
                )
                payment_intent_id = payment_intent.id
                client_secret = payment_intent.client_secret
            # Crear registro de Pago en BD (estado PENDIENTE)
            # Nota: usuario_password almacenará el hasheado (para compatibilidad con modelo Pago)
            pago = Pago.objects.create(
                empresa_slug=serializer.validated_data['empresa_slug'],
                empresa_nombre=serializer.validated_data['empresa_nombre'],
                usuario_email=serializer.validated_data['usuario_email'],
                usuario_nombres=serializer.validated_data['usuario_nombres'],
                usuario_apellidos=serializer.validated_data.get('usuario_apellidos', ''),
                usuario_password=make_password(serializer.validated_data['usuario_password']),
                plan=plan,
                amount_centavos=plan.precio_centavos,
                moneda=settings.STRIPE_CURRENCY.upper(),
                stripe_payment_intent_id=payment_intent_id,
                stripe_customer_id=customer_id,
                estado='PENDIENTE',
                metadata={
                    'ip': self._get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            # Preparar respuesta
            response_serializer = PaymentIntentResponseSerializer({
                'pago_id': pago.id,
                'payment_intent_id': payment_intent_id,
                'client_secret': client_secret,
                'amount_centavos': plan.precio_centavos,
                'moneda': settings.STRIPE_CURRENCY.lower(),
                'empresa_nombre': pago.empresa_nombre,
                'usuario_email': pago.usuario_email,
            })
            return Response({
                'success': True,
                'paymentIntentId': payment_intent_id,
                'clientSecret': client_secret,
                'paymentIntent': response_serializer.data,
            }, status=status.HTTP_200_OK)
        except stripe.error.StripeError as e:
            return Response(
                {'error': f'Error en Stripe: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'Error al crear el pago: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    @action(detail=False, methods=["post"])
    def confirmar_pago(self, request):
        """ Confirma un pago exitoso y crea la empresa con su usuario admin. """
        serializer = ConfirmarPagoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment_intent_id = serializer.validated_data['payment_intent_id']
            
            # Obtener el pago de la BD
            pago = Pago.objects.get(
                stripe_payment_intent_id=payment_intent_id,
                estado='PENDIENTE'
            )

            # En desarrollo, asumir que el pago es exitoso automáticamente
            # En producción, verificar el estado en Stripe
            if settings.DEBUG:
                # Modo desarrollo: asumir pago exitoso
                payment_intent_status = 'succeeded'
            else:
                # Modo producción: verificar en Stripe
                payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
                payment_intent_status = payment_intent.status
            
            if payment_intent_status != 'succeeded':
                return Response(
                    {
                        'error': f'El pago aún no está completado. Estado: {payment_intent_status}',
                        'payment_intent_status': payment_intent_status
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Usar transacción para garantizar consistencia
            with transaction.atomic():
                logger.info(f"Iniciando creación de empresa para pago: {payment_intent_id}")
                # 1. Crear Empresa
                empresa = Empresa.objects.create(
                    nombre=pago.empresa_nombre,
                    slug=pago.empresa_slug,
                    estado='ACTIVA',
                    suscripcion_hasta=timezone.now() + timedelta(days=pago.plan.duracion_dias)
                )
                logger.info(f"Empresa creada: {empresa.id} - {empresa.slug}")
                # 2. Crear Usuario principal (sin rol aún)
                usuario_admin = Usuario(
                    empresa=empresa,
                    email=pago.usuario_email,
                    nombres=pago.usuario_nombres,
                    apellidos=pago.usuario_apellidos or '',
                    password=pago.usuario_password,  # Ya viene hasheado de Pago
                    is_active=True
                )
                usuario_admin.save()
                logger.info(f"Usuario creado: {usuario_admin.id} - {usuario_admin.email}")
                # 3. Configurar automáticamente los 4 roles base y asignar ADMIN al usuario
                setup_resultado = setup_empresa_nueva(empresa, usuario_admin)
                logger.info(f"Setup resultado: {setup_resultado}")
                if not setup_resultado['exito']:
                    # Si falla la configuración de roles, lanzar excepción para revertir transacción
                    raise Exception(f"Error al configurar roles: {setup_resultado.get('error', 'Desconocido')}")
                # 4. Crear Suscripción
                inicio = timezone.now()
                fin = inicio + timedelta(days=pago.plan.duracion_dias)
                suscripcion = Suscripcion.objects.create(
                    empresa=empresa,
                    plan=pago.plan,
                    inicio=inicio,
                    fin=fin,
                    estado='ACTIVA',
                    referencia_pago=payment_intent_id
                )
                logger.info(f"Suscripción creada: {suscripcion.id}")
                # 5. Marcar pago como completado
                pago.estado = 'COMPLETADO'
                pago.empresa = empresa
                pago.processed_at = timezone.now()
                pago.save()
                logger.info(f"Pago marcado como completado")
                # Auditoría: registro de empresa confirmado
                registrar_evento_on_commit(
                    empresa=empresa,
                    accion=AccionAuditoria.REGISTRO_EMPRESA_CONFIRMADO,
                    usuario=usuario_admin,
                    entidad_tipo="Empresa",
                    entidad_id=empresa.id,
                    descripcion=f"Pago confirmado para nueva empresa {empresa.nombre}",
                    metadata={
                        "empresa_id": str(empresa.id),
                        "empresa_slug": empresa.slug,
                        "payment_intent_id": payment_intent_id,
                        "pago_id": str(pago.id),
                        "plan_id": str(pago.plan.id),
                        "plan_nombre": pago.plan.nombre,
                    }
                )
                # Auditoría: empresa registrada
                registrar_evento_on_commit(
                    empresa=empresa,
                    accion=AccionAuditoria.EMPRESA_REGISTRADA,
                    usuario=usuario_admin,
                    entidad_tipo="Empresa",
                    entidad_id=empresa.id,
                    descripcion=f"Nueva empresa registrada: {empresa.nombre}",
                    metadata={
                        "empresa_id": str(empresa.id),
                        "empresa_slug": empresa.slug,
                        "usuario_admin_id": str(usuario_admin.id),
                        "usuario_admin_email": usuario_admin.email,
                    }
                )  
                # Auditoría: suscripción inicial activada
                registrar_evento_on_commit(
                    empresa=empresa,
                    accion=AccionAuditoria.SUSCRIPCION_INICIAL_ACTIVADA,
                    usuario=usuario_admin,
                    entidad_tipo="Suscripcion",
                    entidad_id=suscripcion.id,
                    descripcion=f"Suscripción inicial activada: {pago.plan.nombre}",
                    metadata={
                        "plan_id": str(pago.plan.id),
                        "plan_nombre": pago.plan.nombre,
                        "inicio": suscripcion.inicio.isoformat(),
                        "fin": suscripcion.fin.isoformat(),
                    }
                )
            logger.info(f"Empresa registrada exitosamente: {empresa.slug}")
            return Response({
                'success': True,
                'mensaje': 'Pago confirmado y empresa creada',
                'empresa': {
                    'id': str(empresa.id),
                    'slug': empresa.slug,
                    'nombre': empresa.nombre,
                },
                'usuario': {
                    'id': str(usuario_admin.id),
                    'email': usuario_admin.email,
                },
                'suscripcion_hasta': suscripcion.fin,
                'setup_detalles': {
                    'roles_totales': len(setup_resultado['roles_creados']),
                    'roles_nuevos': sum(1 for r in setup_resultado['roles_creados'] if r['creado']),
                }
            }, status=status.HTTP_200_OK)
        except Pago.DoesNotExist:
            logger.error(f"Pago no encontrado o ya procesado: {payment_intent_id}")
            return Response(
                {'error': 'Pago no encontrado o ya procesado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            logger.error(f"Error de Stripe: {str(e)}")
            return Response(
                {'error': f'Error al verificar pago en Stripe: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception(f"Error al procesar pago - Detalles: {str(e)}")
            return Response(
                {'success': False, 'error': f'Error al procesar pago: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    @action(detail=False, methods=["post"])
    def estado_pago(self, request):
        """ Obtiene el estado de un pago. POST /api/pagos/estado_pago/ """
        payment_intent_id = request.data.get('payment_intent_id')
        if not payment_intent_id:
            return Response(
                {'error': 'payment_intent_id requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            pago = Pago.objects.get(stripe_payment_intent_id=payment_intent_id)
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            return Response({
                'pago_id': str(pago.id),
                'pago_estado': pago.estado,
                'payment_intent_status': payment_intent.status,
                'empresa_nombre': pago.empresa_nombre,
                'empresa_slug': pago.empresa_slug if pago.empresa else None,
                'amount_centavos': pago.amount_centavos,
                'moneda': pago.moneda,
            }, status=status.HTTP_200_OK)
        except Pago.DoesNotExist:
            return Response(
                {'error': 'Pago no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {'error': f'Error en Stripe: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    def _get_client_ip(self, request):
        """Obtiene la IP del cliente."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
