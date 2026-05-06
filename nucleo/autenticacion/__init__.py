from rest_framework_simplejwt.authentication import JWTAuthentication


class OptionalJWTAuthentication(JWTAuthentication):
    """Permite requests anonimos o autenticados con JWT."""

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None
        return super().authenticate(request)

