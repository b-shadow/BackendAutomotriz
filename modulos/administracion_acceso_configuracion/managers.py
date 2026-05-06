"""
Managers personalizados para modelos de autenticación.
"""
from django.contrib.auth.models import BaseUserManager


class UsuarioManager(BaseUserManager):
    """
    Manager personalizado para Usuario.
    
    Soporta creación de usuarios filtrando por empresa.
    Adapta el flujo multi-tenant de Django auth.
    """
    
    def create_usuario(self, email, password, empresa, nombres="", apellidos="", **extra_fields):
        """
        Crea un usuario regular en una empresa específica.
        
        Valores por defecto seguros:
        - is_active: True (usuario puede iniciar sesión)
        - is_staff: False (no acceso a panel admin)
        - is_superuser: False (sin permisos de admin)
        
        Args:
            email: Email único dentro de la empresa
            password: Contraseña sin hashar
            empresa: Instancia o ID de Empresa
            nombres: Nombres del usuario
            apellidos: Apellidos del usuario
            **extra_fields: Otros campos del modelo
        
        Returns:
            Usuario creado
        """
        if not email:
            raise ValueError("El email es requerido")
        
        if not empresa:
            raise ValueError("La empresa es requerida")
        
        # Valores por defecto seguros para usuarios regulares
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_staff", False)  # Los usuarios regulares no tienen acceso a admin
        extra_fields.setdefault("is_superuser", False)  # Solo para superusuarios
        
        # Normalizar email
        email = self.normalize_email(email)
        
        # Crear usuario
        usuario = self.model(
            email=email,
            empresa=empresa,
            nombres=nombres,
            apellidos=apellidos,
            **extra_fields
        )
        
        # Hasear contraseña
        usuario.set_password(password)
        usuario.save(using=self._db)
        
        return usuario

    def create_user(self, email, password=None, empresa=None, nombres="", apellidos="", **extra_fields):
        """
        Compatibilidad con el contrato estándar de Django.

        Muchos tests y utilidades esperan `objects.create_user(...)`.
        Internamente delega al flujo multi-tenant `create_usuario`.
        """
        if password is None:
            raise ValueError("La contraseña es requerida")
        return self.create_usuario(
            email=email,
            password=password,
            empresa=empresa,
            nombres=nombres,
            apellidos=apellidos,
            **extra_fields,
        )
    
    def create_superuser(self, email, password, empresa=None, nombres="", apellidos="", **extra_fields):
        """
        Crea un superusuario (admin del SaaS).
        
        En arquitectura multi-tenant, TODOS los usuarios deben pertenecer a una empresa.
        
        El superusuario DEBE tener:
        - is_staff=True (acceso al panel admin)
        - is_superuser=True (todos los permisos)
        
        IMPORTANTE:
        - A diferencia de Django estándar, empresa es REQUERIDO aquí
        - Es mejor crear usuarios admin por empresa usando create_usuario() 
          o el management command
        
        Parámetros:
        -----------
        email : str
            Email único dentro de la empresa
        password : str
            Contraseña sin hashar
        empresa : Empresa
            Instancia o ID de Empresa (REQUERIDO)
        nombres : str
            Nombres del usuario
        apellidos : str
            Apellidos del usuario
        **extra_fields : dict
            Otros campos; is_staff e is_superuser se establecerán automáticamente
        
        Raises:
        -------
        ValueError
            Si email, empresa, is_staff o is_superuser no son válidos
        
        Returns:
        --------
        Usuario
            El superusuario creado
        """
        if not email:
            raise ValueError("El email es requerido")
        
        if not empresa:
            raise ValueError("La empresa es requerida para crear un superusuario")
        
        # OBLIGATORIO: is_staff y is_superuser deben ser True para un superusuario
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        
        # VALIDACIÓN: Si se intenta pasar is_staff=False o is_superuser=False, error
        if extra_fields.get("is_staff") != True:
            raise ValueError("El superusuario debe tener is_staff=True")
        
        if extra_fields.get("is_superuser") != True:
            raise ValueError("El superusuario debe tener is_superuser=True")
        
        email = self.normalize_email(email)
        
        return self.create_usuario(
            email=email,
            password=password,
            empresa=empresa,
            nombres=nombres,
            apellidos=apellidos,
            **extra_fields
        )
