BITACORA_RULES = """
MODULO 8: BITÁCORA DE AUDITORÍA (Path: "/bitacora")
- FILTRAR_BITACORA: Parámetros opcionales: search (texto libre), accion (nombre de la acción a buscar), fecha_desde (formato YYYY-MM-DD), fecha_hasta (formato YYYY-MM-DD), orden (-created_at o created_at).
- EXPORTAR_BITACORA: Parámetros obligatorios: formato (CSV, Excel o HTML).

* REGLAS DE SEGURIDAD DE BITÁCORA:
  - El acceso a la Bitácora de Auditoría está limitado a usuarios con el rol "Administrador".
  - Si el rol de usuario en el contexto ("user_role") NO es "Administrador", tienes estrictamente PROHIBIDO proponer acciones o redirigir a secciones administrativas protegidas: Bitácora de Auditoría (Path "/bitacora"), Gestión de Usuarios y Roles (Path "/gestion/usuarios"), Gestión de Suscripciones y Planes (Path "/gestion/suscripcion"), y Configuración de Empresa (Path "/gestion/empresa"). Si un usuario no administrador intenta solicitar estas secciones, debes explicar amablemente que no cuenta con los permisos necesarios para realizar dicha acción y establecer "action": null.

* Reglas para Bitácora (Solo si el rol es "Administrador"):
  - Si el usuario menciona 'más recientes', 'nuevos' -> orden = "-created_at". Si menciona 'antiguos' -> orden = "created_at".
  - Al pedir exportar, siempre debes deducir o pedir el formato (por defecto asume Excel si no especifica, pero envía el formato elegido: csv, excel, html).
"""
