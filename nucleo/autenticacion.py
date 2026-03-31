"""
Autenticación personalizada para permitir endpoints públicos.

La autenticación JWT estándar falla si no hay token válido.
Esta implementación permite que falte un token (retorna None en lugar de excepción).

También valida que el token no fue emitido antes de que el usuario cerrara sesión.
"""
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import TokenAuthentication
from rest_framework import exceptions
from datetime import datetime, timezone


class OptionalJWTAuthentication(JWTAuthentication):
    """
    Autenticación JWT que permite fallos gracefully.
    Si no hay token o el token es inválido, retorna (None, None) en lugar de lanzar error.
    Esto permite que permission_classes=AllowAny maneje el acceso público.
    
    TAMBIÉN valida logout: si user.session_revoked_at está seteado,
    rechaza tokens emitidos ANTES de esa fecha.
    """
    
    def authenticate(self, request):
        """
        Intenta autenticar con JWT. Si falla, retorna None para permitir acceso anónimo.
        Si el usuario cerró sesión (session_revoked_at), rechaza tokens viejos.
        """
        try:
            result = super().authenticate(request)
        except exceptions.AuthenticationFailed:
            # Si falla la autenticación, permitir acceso anónimo (retornar None)
            return None
        except exceptions.APIException:
            # Otros errores de API también se permiten
            return None
        
        if result is None:
            # No hay token en el request
            return None
        
        user, validated_token = result
        
        # Validar que el token no fue emitido antes de que el usuario cerrara sesión
        if user and user.session_revoked_at:
            # token.iat es timestamp (segundos desde epoch)
            token_issued_at = validated_token.get('iat')
            
            if token_issued_at:
                # Convertir timestamp a datetime
                token_issued_datetime = datetime.fromtimestamp(
                    token_issued_at, 
                    tz=timezone.utc
                )
                
                # Si el token fue emitido ANTES de cerrar sesión, rechazarlo
                if token_issued_datetime < user.session_revoked_at:
                    raise exceptions.AuthenticationFailed(
                        "Token ha sido revocado por cierre de sesión"
                    )
        
        # Token válido
        return (user, validated_token)

