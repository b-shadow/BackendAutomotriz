""" Servicio para configuraciÃ³n automÃ¡tica de empresas.
Maneja la creaciÃ³n de roles base y asignaciÃ³n de permisos iniciales
cuando se crea una nueva empresa del taller automotriz.
PROPÃ“SITO:
- Evitar lÃ³gica duplicada en varias vistas
- Garantizar que cada empresa nueva estÃ© lista para operar desde el primer momento
- Crear 6 roles base automÃ¡ticamente: ADMIN, USUARIO, MECÃNICO, ASESOR DE SERVICIO, ADMINISTRATIVO, ALMACENERO
- Asignar el rol ADMIN al usuario principal"""
from django.db import transaction
from modulos.administracion_acceso_configuracion.models import Empresa, Rol, Usuario
ROLES_BASE_SISTEMA = [
    {
        "nombre": "ADMIN",
        "descripcion": "Administrador con acceso total al sistema y gestiÃ³n de empresa",
        "es_sistema": True,
    },
    {
        "nombre": "USUARIO",
        "descripcion": "Cliente que consulta y gestiona su informaciÃ³n y servicios",
        "es_sistema": True,
    },
    {
        "nombre": "MECÃNICO",
        "descripcion": "Ejecuta y reporta el trabajo tÃ©cnico del vehÃ­culo",
        "es_sistema": True,
    },
    {
        "nombre": "ASESOR DE SERVICIO",
        "descripcion": "Recibe al cliente, organiza el servicio y coordina el trabajo tÃ©cnico",
        "es_sistema": True,
    },
    {
        "nombre": "ADMINISTRATIVO",
        "descripcion": "Cobra, factura, registra ventas y controla la parte econÃ³mica operativa",
        "es_sistema": True,
    },
    {
        "nombre": "ALMACENERO",
        "descripcion": "Controla inventario, repuestos e insumos",
        "es_sistema": True,
    },
]

@transaction.atomic
def setup_empresa_nueva(empresa: Empresa, usuario_principal: Usuario) -> dict:
    """ Configura automÃ¡ticamente una empresa nueva con sus 6 roles base. """
    
    try:
        # 1. Crear los 6 roles base para la empresa
        roles_resultado = []
        
        for rol_config in ROLES_BASE_SISTEMA:
            rol, creado = Rol.objects.get_or_create(
                empresa=empresa,
                nombre=rol_config["nombre"],
                defaults={
                    "descripcion": rol_config["descripcion"],
                    "es_sistema": rol_config["es_sistema"],
                }
            )
            
            roles_resultado.append({
                "nombre": rol.nombre,
                "creado": creado,
                "rol_id": str(rol.id),
            })
        
        # 2. Obtener el rol ADMIN para asignarlo al usuario principal
        rol_admin = Rol.objects.get(
            empresa=empresa,
            nombre="ADMIN"
        )
        
        # 3. Asignar el rol ADMIN al usuario principal
        usuario_principal.rol = rol_admin
        usuario_principal.save(update_fields=["rol", "updated_at"])
        
        # 4. Preparar resultado exitoso
        return {
            "empresa_id": str(empresa.id),
            "empresa_nombre": empresa.nombre,
            "empresa_slug": empresa.slug,
            "roles_creados": roles_resultado,
            "usuario_principal_id": str(usuario_principal.id),
            "usuario_principal_email": usuario_principal.email,
            "usuario_rol_asignado": rol_admin.nombre,
            "exito": True,
            "mensaje": f"Empresa '{empresa.nombre}' configurada correctamente con 6 roles base (ADMIN, USUARIO, MECÃNICO, ASESOR DE SERVICIO, ADMINISTRATIVO, ALMACENERO). Usuario principal asignado como ADMIN."
        }
    
    except Exception as e:
        # Si ocurre un error, la transacciÃ³n se revierte automÃ¡ticamente
        return {
            "empresa_id": str(empresa.id),
            "empresa_nombre": empresa.nombre,
            "roles_creados": [],
            "usuario_principal_id": str(usuario_principal.id),
            "exito": False,
            "error": str(e),
            "mensaje": f"Error al configurar empresa: {str(e)}"
        }


def crear_rol_personalizado(empresa: Empresa, nombre: str, descripcion: str = "") -> tuple:
    """Utilidad adicional para crear roles personalizados (no del sistema).
    Ãštil cuando los admins de empresa quieren crear roles adicionales."""
    if not nombre or not nombre.strip():
        raise ValueError("El nombre del rol no puede estar vacÃ­o")
    
    return Rol.objects.get_or_create(
        empresa=empresa,
        nombre=nombre.strip(),
        defaults={
            "descripcion": descripcion.strip() if descripcion else "",
            "es_sistema": False,
        }
    )

