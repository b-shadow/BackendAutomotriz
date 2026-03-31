"""Servicio centralizado de auditoría para el sistema SaaS."""
import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from uuid import UUID
from django.db import transaction
from django.utils import timezone
from app.models import Auditoria, Empresa, Usuario

logger = logging.getLogger(__name__)

# PATRONES DE SEGURIDAD

CAMPOS_SENSIBLES = {
    'password', 'passwd', 'pwd', 'contraseña',
    'access_token', 'refresh_token', 'token',
    'api_key', 'api_secret', 'secret',
    'client_secret', 'client_id',
    'cvc', 'cvv', 'card_number', 'tarjeta',
    'authorization', 'bearer',
    'stripe_key', 'stripe_secret',
}

CAMPOS_SENSIBLES_PARCIAL = {
    'hash', 'hashed',  # Hashes de contraseña
    'session', 'jwt',
    'oauth',
}

def _es_campo_sensible(clave: str) -> bool:
    """
    Determina si una clave debe ser filtrada por seguridad.
    """
    clave_lower = clave.lower()
    # Búsqueda exacta
    if clave_lower in CAMPOS_SENSIBLES:
        return True
    # Búsqueda parcial (substrings)
    for patron in CAMPOS_SENSIBLES_PARCIAL:
        if patron in clave_lower:
            return True 
    return False

# NORMALIZACIÓN Y LIMPIEZA

def normalizar_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not metadata:
        return {}
    if not isinstance(metadata, dict):
        logger.warning(f"metadata no es dict: {type(metadata)}")
        return {}
    normalizado = {}
    for clave, valor in metadata.items():
        # Filtrar campos sensibles
        if _es_campo_sensible(clave):
            logger.debug(f"Filtrando campo sensible en auditoría: {clave}")
            continue
        # Convertir tipos no serializables a string
        try:
            if isinstance(valor, UUID):
                normalizado[clave] = str(valor)
            elif isinstance(valor, (datetime, date)):
                if isinstance(valor, datetime):
                    normalizado[clave] = valor.isoformat()
                else:
                    normalizado[clave] = valor.isoformat()
            elif isinstance(valor, dict):
                # Recursivamente normalizar dicts anidados
                normalizado[clave] = normalizar_metadata(valor)
            elif isinstance(valor, (list, tuple)):
                # Normalizar elementos de listas
                normalizado[clave] = [
                    normalizar_metadata({"_item": item}).get("_item", item)
                    if isinstance(item, dict) else item
                    for item in valor
                ]
            elif valor is None or isinstance(valor, (str, int, float, bool)):
                normalizado[clave] = valor
            else:
                # Intentar convertir a string como último recurso
                normalizado[clave] = str(valor)
        except Exception as e:
            logger.warning(f"Error normalizando campo {clave}: {e}")
            normalizado[clave] = str(valor)
    return normalizado

def obtener_ip_request(request) -> Optional[str]:
    """ Obtiene la IP del cliente desde el request. """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # X-Forwarded-For puede contener múltiples IPs, tomar la primera
        ip = x_forwarded_for.split(',')[0].strip()
        return ip
    return request.META.get('REMOTE_ADDR')

def obtener_user_agent_request(request) -> Optional[str]:
    """ Obtiene el User-Agent del cliente desde el request. """
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    if user_agent:
        # Truncar a 500 caracteres
        return user_agent[:500]
    return None

# FUNCIONES PÚBLICAS DE AUDITORÍA

def registrar_evento_auditoria(
    empresa: Empresa,
    accion: str,
    usuario: Optional[Usuario] = None,
    entidad_tipo: Optional[str] = None,
    entidad_id: Optional[UUID] = None,
    descripcion: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[Auditoria]:
    """ Registra un evento de auditoría en la base de datos. """
    try:
        # Validaciones básicas
        if not empresa or not isinstance(empresa, Empresa):
            logger.error(f"registrar_evento_auditoria: empresa inválida o None")
            return None
        if not accion or not isinstance(accion, str):
            logger.error(f"registrar_evento_auditoria: accion vacía o inválida")
            return None
        # Normalizar metadata
        metadata_limpia = normalizar_metadata(metadata)
        # Crear evento
        evento = Auditoria.objects.create(
            empresa=empresa,
            usuario=usuario,
            accion=accion,
            entidad_tipo=entidad_tipo,
            entidad_id=entidad_id,
            descripcion=descripcion,
            metadata=metadata_limpia,
            ip=ip,
            user_agent=user_agent,
        )
        logger.debug(f"Evento auditoría creado: {accion} en {empresa.slug}")
        return evento
    except Exception as e:
        logger.exception(f"Error registrando evento auditoría [{accion}]: {e}")
        return None

def registrar_evento_desde_request(
    request,
    empresa: Empresa,
    accion: str,
    usuario: Optional[Usuario] = None,
    entidad_tipo: Optional[str] = None,
    entidad_id: Optional[UUID] = None,
    descripcion: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Auditoria]:
    """ Registra un evento de auditoría extrayendo IP y User-Agent del request. """
    ip = obtener_ip_request(request)
    user_agent = obtener_user_agent_request(request)
    return registrar_evento_auditoria(
        empresa=empresa,
        accion=accion,
        usuario=usuario,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        descripcion=descripcion,
        metadata=metadata,
        ip=ip,
        user_agent=user_agent,
    )

def registrar_evento_on_commit(
    empresa: Empresa,
    accion: str,
    usuario: Optional[Usuario] = None,
    entidad_tipo: Optional[str] = None,
    entidad_id: Optional[UUID] = None,
    descripcion: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """ Registra un evento de auditoría de forma diferida usando transaction.on_commit(). """
    def _registrar():
        registrar_evento_auditoria(
            empresa=empresa,
            accion=accion,
            usuario=usuario,
            entidad_tipo=entidad_tipo,
            entidad_id=entidad_id,
            descripcion=descripcion,
            metadata=metadata,
            ip=ip,
            user_agent=user_agent,
        )
    try:
        transaction.on_commit(_registrar)
    except Exception as e:
        logger.exception(f"Error en registrar_evento_on_commit: {e}")

# HELPERS PARA CAMBIOS/DIFFS
def construir_cambios(
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
    campos_permitidos: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """ Compara dos diccionarios y construye una estructura de cambios.
    Retorna un diccionario con los campos que cambiaron, mostrando antes y después.
    Args:
        old_data: Datos anteriores
        new_data: Datos nuevos
        campos_permitidos: Lista de campos a considerar (None = todos)
    Returns:
        {
            "campos_modificados": {
                "email": {"antes": "viejo@mail.com", "despues": "nuevo@mail.com"},
                "nombres": {"antes": "Juan", "despues": "John"},
            }
        } """
    campos_modificados = {}
    old_data = old_data or {}
    new_data = new_data or {}
    # Determinar campos a comparar
    if campos_permitidos:
        campos_a_revisar = set(campos_permitidos)
    else:
        campos_a_revisar = set(old_data.keys()) | set(new_data.keys())
    for campo in campos_a_revisar:
        # Filtrar campos sensibles
        if _es_campo_sensible(campo):
            continue  
        valor_viejo = old_data.get(campo)
        valor_nuevo = new_data.get(campo)    
        # Solo incluir si cambió
        if valor_viejo != valor_nuevo:
            campos_modificados[campo] = {
                "antes": valor_viejo,
                "despues": valor_nuevo,
            }
   
    return {
        "campos_modificados": campos_modificados
    }

# ENUMS Y CONSTANTES DE ACCIONES
class AccionAuditoria:
    # Autenticación Tenant
    USUARIO_REGISTRADO_TENANT = "Usuario registrado"
    USUARIO_LOGIN_TENANT = "Iniciar Sesión"
    USUARIO_LOGOUT_TENANT = "Cerrar Sesión"
    # Registro de Empresa con Pago
    REGISTRO_EMPRESA_CONFIRMADO = "Registro de empresa confirmado"
    EMPRESA_REGISTRADA = "Empresa registrada"
    SUSCRIPCION_INICIAL_ACTIVADA = "Suscripcion inicial activada"
    # Usuarios y Roles
    USUARIO_CREADO = "Usuario creado"
    USUARIO_ROL_CAMBIADO = "Usuario rol cambiado"
    USUARIO_DESACTIVADO = "Usuario desactivado"
    USUARIO_ACTIVADO = "Usuario activado"
    PERFIL_ACTUALIZADO = "Perfil actualizado"
    PASSWORD_CAMBIADO = "Password cambiado"
    PREFERENCIAS_NOTIFICACION_ACTUALIZADAS = "Preferencias de notificacion actualizadas"
    USUARIO_ELIMINADO = "Usuario eliminado"
    # Suscripciones
    SUSCRIPCION_CAMBIO_PROGRAMADO = "Suscripcion cambio programado"
    SUSCRIPCION_CAMBIO_CANCELADO = "Suscripcion cambio cancelado"
    SUSCRIPCION_RENOVADA = "Suscripcion renovada"
    SUSCRIPCION_PAGO_CONFIRMADO_CAMBIO = "Suscripcion pago confirmado cambio"
    SUSCRIPCION_PLAN_PENDIENTE_APLICADO = "Suscripcion plan pendiente aplicado"
    
    # Vehículos
    VEHICULO_CREADO = "Vehiculo creado"
    VEHICULO_ACTUALIZADO = "Vehiculo actualizado"
    VEHICULO_ESTADO_CAMBIADO = "Vehiculo estado cambiado"
    
    # Servicios Catálogo
    SERVICIO_CATALOGO_CREADO = "Servicio de catalogo creado"
    SERVICIO_CATALOGO_ACTUALIZADO = "Servicio de catalogo actualizado"
    SERVICIO_CATALOGO_ESTADO_CAMBIADO = "Servicio de catalogo estado cambiado"
    
    # Espacios de Trabajo
    ESPACIO_TRABAJO_CREADO = "Espacio de trabajo creado"
    ESPACIO_TRABAJO_ACTUALIZADO = "Espacio de trabajo actualizado"
    ESPACIO_TRABAJO_ESTADO_CAMBIADO = "Espacio de trabajo, estado cambiado"
    ESPACIO_TRABAJO_ACTIVO_CAMBIADO = "Espacio de trabajo, activo cambiado"
    
    # Horarios de Espacios de Trabajo
    HORARIO_ESPACIO_CREADO = "Horario de espacio creado"
    HORARIO_ESPACIO_ACTUALIZADO = "Horario de espacio actualizado"
    HORARIO_ESPACIO_ACTIVO_CAMBIADO = "Horario de espacio, activo cambiado"
    HORARIO_ESPACIO_ELIMINADO = "Horario de espacio eliminado"
    
    # Planes de Vehículo (CU22)
    PLAN_VEHICULO_CREADO = "Plan de vehículo creado"
    PLAN_VEHICULO_ACTUALIZADO = "Plan de vehículo actualizado"
    PLAN_VEHICULO_ESTADO_CAMBIADO = "Plan de vehículo, estado cambiado"
    
    # Detalles de Planes de Vehículo (CU22)
    PLAN_VEHICULO_DETALLE_CREADO = "Detalle de plan de vehículo creado"
    PLAN_VEHICULO_DETALLE_ACTUALIZADO = "Detalle de plan de vehículo actualizado"
    PLAN_VEHICULO_DETALLE_ESTADO_CAMBIADO = "Detalle de plan de vehículo, estado cambiado"
    PLAN_VEHICULO_DETALLE_ELIMINADO = "Detalle de plan de vehículo eliminado"
    
    # Citas (CU18)
    CITA_CREADA = "Cita creada"
    CITA_ACTUALIZADA = "Cita actualizada"
    CITA_ELIMINADA = "Cita eliminada"
