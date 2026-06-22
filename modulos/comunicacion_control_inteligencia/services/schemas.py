from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

class ActionDetails(BaseModel):
    """
    Representa una acción técnica a ejecutar en la plataforma (Backend o Frontend).
    """
    type: Literal[
        "CAMBIAR_NOMBRES_PERSONALES", "CAMBIAR_TELEFONO", "CAMBIAR_CONTRASENA",
        "ACTUALIZAR_PREFERENCIAS", "CAMBIAR_NOMBRE_EMPRESA", "COMPRAR_PLAN",
        "RELLENAR_PAGO", "CANCELAR_CAMBIO", "REGISTRAR_VEHICULO", "BUSCAR_VEHICULO",
        "AGREGAR_SERVICIO", "REGISTRAR_ESPACIO", "EDITAR_ESPACIO", "VER_HORARIOS_ESPACIO",
        "AGREGAR_HORARIO_ESPACIO", "EDITAR_HORARIO_ESPACIO", "CREAR_CITA", "FILTRAR_CITAS",
        "BUSCAR_PLAN_VEHICULO", "VER_PLAN_VEHICULO", "EDITAR_PLAN_VEHICULO",
        "CAMBIAR_ESTADO_PLAN_VEHICULO", "AGREGAR_DETALLE_PLAN_VEHICULO",
        "FILTRAR_BITACORA", "EXPORTAR_BITACORA", "VER_REPORTE_GLOBAL",
        "VER_REPORTE_VEHICULO", "VER_REPORTE_PRESUPUESTO", "VER_REPORTE_INVENTARIO",
        "EXPORTAR_REPORTE", "CREAR_CATEGORIA_INVENTARIO", "CREAR_ITEM_INVENTARIO",
        "CREAR_PROVEEDOR", "AGREGAR_ITEM_COMPRA", "CONFIGURAR_BACKUP", 
        "CREAR_USUARIO", "CAMBIAR_ROL_USUARIO", "AGREGAR_ITEM_VENTA",
        "EMITIR_FACTURA", "CONSULTAR_CAJA"
    ] = Field(..., description="El tipo de acción EXACTA a realizar. No uses otros valores.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parámetros extraídos de la conversación, respetando los nombres esperados para la acción.")
    status: Literal["PENDIENTE", "EJECUTADA"] = Field(default="PENDIENTE", description="Usa PENDIENTE a medida que vayas llenando los datos del usuario visualmente en su pantalla. Usa EJECUTADA ÚNICAMENTE cuando el usuario haya confirmado explícitamente que todo está correcto y te dé la orden de guardar/enviar.")

class IAAssistantResponse(BaseModel):
    """
    Esquema maestro de respuesta para la Inteligencia Artificial.
    Asegura que el LLM nunca devuelva un JSON inválido y entienda cuándo pedir datos faltantes.
    """
    message: str = Field(..., description="El mensaje conversacional para el usuario. IMPORTANTE: Si faltan datos, pídelos amigablemente aquí.")
    options: Optional[List[str]] = Field(default=None, description="Botones de respuesta rápida sugeridos para el usuario (máximo 3). Ej: ['Sí, continuar', 'Cancelar']")
    suggested_actions: Optional[List[str]] = Field(default=None, description="Sugerencias conceptuales (ej: ['Ver inventario', 'Crear cita']).")
    action: Optional[ActionDetails] = Field(None, description="El objeto de acción estructural. DEBES generarlo con status='PENDIENTE' incluso si faltan datos, para que el frontend pueda ir prellenando la pantalla.")
    ui_type: Optional[Literal["text", "select_list", "checkboxes"]] = Field(None, description="Determina si el frontend debe mostrar una interfaz especial al usuario.")

class IntentClassification(BaseModel):
    """
    Esquema utilizado por el Agente Enrutador para clasificar la intención del usuario.
    """
    intent: Literal[
        "VEHICULOS_PLANES", "CITAS", "CONFIGURACION", "PERFIL_USUARIO", "REPORTES_BITACORA",
        "INVENTARIO", "PROVEEDORES", "COMPRAS", "USUARIOS", "BACKUP", "FINANZAS_VENTAS", "GENERAL"
    ] = Field(..., description="El módulo principal de la plataforma al que corresponde el mensaje del usuario.")
