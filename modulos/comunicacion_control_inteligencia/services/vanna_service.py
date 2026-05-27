import os
from typing import List, Dict, Any, Optional
import json
import re
from vanna.base import VannaBase
from groq import Groq
from django.conf import settings
from django.db import connection

class VannaAutomotrizService(VannaBase):
    """
    Servicio personalizado de Vanna AI que utiliza Groq como LLM y
    PostgreSQL (vía Django connection) para ejecutar las consultas SQL.
    Aplica seguridad multi-tenant para asegurar el aislamiento de datos.
    """
    
    def __init__(self, tenant_id: int):
        super().__init__(config=None)
        
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.tenant_id = tenant_id
        
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no está configurada en las variables de entorno.")
            
        self.groq_client = Groq(api_key=self.api_key)
        
        # Dialecto para generar SQL correcto
        self.dialect = "PostgreSQL"
        
        # Almacenamiento local simple para DDL (simulando memoria RAG sin pgvector)
        # En producción real esto podría leerse de la base de datos o un VectorStore
        self._ddl_cache = []
        self._sql_cache = []
        
        self._initialize_context()

    def _initialize_context(self):
        """
        Extrae dinámicamente el DDL de los modelos relevantes de Django para
        entrenar el contexto de Vanna.
        """
        from django.apps import apps
        
        modelos_permitidos = [
            'vehiculos_servicios_plan_citas.Vehiculo',
            'vehiculos_servicios_plan_citas.Cita',
            'vehiculos_servicios_plan_citas.CitaDetalle',
            'vehiculos_servicios_plan_citas.ServicioCatalogo',
            'atencion_tecnica_ejecucion.PresupuestoCita',
            'atencion_tecnica_ejecucion.PresupuestoDetalle',
            'atencion_tecnica_ejecucion.OrdenTrabajoGlobal',
            'atencion_tecnica_ejecucion.OrdenTrabajoGlobalMecanico',
            'atencion_tecnica_ejecucion.OrdenTrabajoDetalle',
            'inventario_proveedores_administracion.CategoriaInventario',
            'inventario_proveedores_administracion.ItemInventario',
            'inventario_proveedores_administracion.Compra',
            'inventario_proveedores_administracion.CompraDetalle',
            'inventario_proveedores_administracion.PagoTaller',
            'inventario_proveedores_administracion.Factura',
            'inventario_proveedores_administracion.VentaMostrador',
            'inventario_proveedores_administracion.VentaMostradorDetalle',
            'administracion_acceso_configuracion.Usuario',
            'administracion_acceso_configuracion.Rol'
        ]
        
        for app_model in modelos_permitidos:
            try:
                app_label, model_name = app_model.split('.')
                model = apps.get_model(app_label, model_name)
                table_name = model._meta.db_table
                
                # Construir un pseudo-DDL basado en los campos del modelo
                columnas = []
                for field in model._meta.fields:
                    tipo = field.get_internal_type()
                    if tipo == 'ForeignKey':
                        tipo_sql = 'UUID' if field.related_model._meta.pk.get_internal_type() == 'UUIDField' else 'INTEGER'
                    elif tipo in ['CharField', 'TextField']:
                        tipo_sql = 'VARCHAR'
                    elif tipo in ['IntegerField', 'BigAutoField']:
                        tipo_sql = 'INTEGER'
                    elif tipo in ['DecimalField', 'FloatField']:
                        tipo_sql = 'DECIMAL'
                    elif tipo in ['DateTimeField', 'DateField']:
                        tipo_sql = 'TIMESTAMP'
                    elif tipo == 'BooleanField':
                        tipo_sql = 'BOOLEAN'
                    elif tipo == 'UUIDField':
                        tipo_sql = 'UUID'
                    else:
                        tipo_sql = 'VARCHAR'
                        
                    ref = ""
                    if field.is_relation and field.related_model:
                        ref = f" REFERENCES {field.related_model._meta.db_table}({field.related_model._meta.pk.column})"
                        
                    comentario = f" -- {getattr(field, 'verbose_name', '')}"
                    if getattr(field, 'help_text', ''):
                        comentario += f": {field.help_text}"
                        
                    columnas.append(f"  {field.column} {tipo_sql}{ref}{comentario}")
                
                ddl = f"CREATE TABLE {table_name} (\n" + ",\n".join(columnas) + "\n);"
                self.add_ddl(ddl)
            except Exception as e:
                print(f"Error cargando contexto para {app_model}: {e}")
                
        # Entrenar Vanna con conocimiento de que SIEMPRE debe filtrar por empresa_id
        self.add_sql(
            question="¿Cuántas citas hay?",
            sql=f"SELECT COUNT(*) FROM citas WHERE empresa_id = '{self.tenant_id}'"
        )
        self.add_sql(
            question="¿Cuáles son los ingresos totales?",
            sql=f"SELECT SUM(total) FROM facturas WHERE empresa_id = '{self.tenant_id}'"
        )
        self.add_sql(
            question="¿Cuáles son los servicios más rentables este mes?",
            sql=f"SELECT sc.nombre, SUM(cd.precio_referencial) as rentabilidad FROM citas_detalles cd JOIN servicios_catalogo sc ON cd.servicio_catalogo_id = sc.id WHERE cd.empresa_id = '{self.tenant_id}' AND cd.created_at >= date_trunc('month', CURRENT_DATE) GROUP BY sc.nombre ORDER BY rentabilidad DESC LIMIT 5"
        )
        self.add_sql(
            question="Lista los 5 clientes con más citas finalizadas en el sistema",
            sql=f"SELECT u.nombres || ' ' || u.apellidos as cliente, COUNT(c.id) as total_citas FROM citas c JOIN usuarios u ON c.cliente_id = u.id WHERE c.empresa_id = '{self.tenant_id}' AND c.estado = 'FINALIZADA' GROUP BY u.nombres, u.apellidos ORDER BY total_citas DESC LIMIT 5"
        )
        self.add_sql(
            question="¿Qué repuestos tienen stock bajo o están por agotarse?",
            sql=f"SELECT i.nombre, i.stock_actual, i.stock_minimo FROM item_inventario i WHERE i.empresa_id = '{self.tenant_id}' AND i.stock_actual <= i.stock_minimo AND i.activo = true ORDER BY i.stock_actual ASC LIMIT 10"
        )
        self.add_sql(
            question="¿Cuál es el ticket promedio?",
            sql=f"SELECT COALESCE(SUM(monto_total), 0) / NULLIF(COUNT(DISTINCT cita_id), 0) AS ticket_promedio FROM pagos_taller WHERE empresa_id = '{self.tenant_id}' AND estado != 'ANULADO'"
        )
        self.add_sql(
            question="¿Cuál es el mecánico más eficiente o que ha resuelto más detalles?",
            sql=f"SELECT u.nombres || ' ' || u.apellidos as mecanico, COUNT(od.id) as detalles_resueltos FROM ordenes_trabajo_detalle od JOIN usuarios u ON od.mecanico_asignado_id = u.id WHERE od.empresa_id = '{self.tenant_id}' AND od.estado = 'FINALIZADO' GROUP BY u.nombres, u.apellidos ORDER BY detalles_resueltos DESC LIMIT 5"
        )
        self.add_sql(
            question="quiero ver los usuarios de esta empresa",
            sql=f"SELECT u.nombres, u.apellidos, r.nombre AS rol FROM usuarios u JOIN roles r ON u.rol_id = r.id WHERE u.empresa_id = '{self.tenant_id}' ORDER BY u.nombres ASC"
        )
        self.add_sql(
            question="listar usuarios con su rol",
            sql=f"SELECT u.nombres, u.apellidos, r.nombre AS rol FROM usuarios u JOIN roles r ON u.rol_id = r.id WHERE u.empresa_id = '{self.tenant_id}' ORDER BY u.nombres ASC"
        )
    def system_message(self, message: str) -> any:
        return {"role": "system", "content": message}

    def user_message(self, message: str) -> any:
        return {"role": "user", "content": message}

    def assistant_message(self, message: str) -> any:
        return {"role": "assistant", "content": message}

    def submit_prompt(self, prompt, **kwargs):
        """
        Sobrescribe el método de inferencia de Vanna para usar Groq.
        Inyectamos fuertemente la regla de empresa_id.
        """
        # Asegurar que Vanna sepa sobre el tenant actual en cada prompt
        tenant_instruction = (
            f"\n\nIMPORTANTE Y CRÍTICO: "
            f"\n1. SEGURIDAD: TODAS las consultas generadas DEBEN incluir la condición `empresa_id = '{self.tenant_id}'` en la cláusula WHERE. "
            f"\n2. JOINS: Si la consulta une varias tablas (JOIN), DEBES usar alias válidos para cada tabla y usar el alias correcto para la columna empresa_id (ej: `alias_tabla.empresa_id = '{self.tenant_id}'`) para evitar ambigüedad. NUNCA uses un alias que no hayas definido en el FROM."
            f"\n3. ESQUEMA ESTRICTO: NUNCA inventes columnas ni uses lógica de negocio alucinada. USA ÚNICAMENTE las columnas descritas en los esquemas DDL (ej. si una tabla tiene `monto_total`, NO uses `total` ni `subtotal` a menos que exista)."
            f"\n4. NOMBRES LEGIBLES: NUNCA incluyas columnas de tipo UUID (como `id`, `vehiculo_id`, `cliente_id`) en tu SELECT final, ni siquiera junto con el nombre. SIEMPRE haz JOIN para traer SOLO el nombre legible (ej. `placa` del vehiculo, `nombres` del cliente). Las tablas finales NO deben tener UUIDs."
            f"\n5. SINTAXIS SQL CORRECTA: Toda columna incluida en el SELECT que NO sea una función de agregación (como COUNT o SUM) DEBE estar incluida explícitamente en la cláusula GROUP BY. Si haces SELECT placa, nombres, COUNT(id), DEBES agrupar por placa, nombres."
            f"\n6. CERO ALUCINACIONES DE COLUMNAS: Nunca asumas que una columna existe en una tabla solo porque suena lógico. Por ejemplo, `citas_detalles` tiene `precio_referencial`, pero `presupuestos_detalle` tiene `precio_unitario`. SIEMPRE revisa el DDL antes de escribir la columna."
            f"\n7. CONTEXTO IMPLÍCITO DE EMPRESA: ASUME SIEMPRE que cualquier pregunta se refiere EXCLUSIVAMENTE a la empresa del usuario. Aunque el usuario no mencione explícitamente 'de mi empresa' o 'de este taller', tú DEBES aplicar el filtro `empresa_id = '{self.tenant_id}'`. NUNCA generes una consulta que busque datos globales de todas las empresas."
            f"\n8. RELACIONES Y JOINS CORRECTOS: Nunca asumas relaciones directas que no existan en el DDL. Por ejemplo, `citas_detalles` NO se relaciona directamente con `vehiculos` ni con `usuarios`. Para obtener el vehículo de un detalle de cita, DEBES hacer JOIN a través de la tabla `citas` (`citas_detalles.cita_id = citas.id` y luego `citas.vehiculo_id = vehiculos.id`). Lo mismo aplica para llegar al cliente."
            f"\n9. RESTRICCIÓN DE KPI ÚNICO (CRÍTICO): Tú generas UNA sola tabla SQL. NUNCA uses UNION ni intentes mezclar datos no relacionados (ej. 'vehículos' y 'finanzas' en la misma tabla). Si el usuario pide varias cosas a la vez en la misma pregunta, ELIGE SOLAMENTE LA PRIMERA y genera la consulta perfecta para esa. Ignora el resto. Es preferible responder 1 cosa bien, que generar un error de sintaxis."
            f"\n10. CAMPOS DE TEXTO DIRECTOS: Los campos llamados `estado`, `tipo`, `origen`, etc., son de tipo VARCHAR y contienen el valor textual (ej. 'FINALIZADA'). NUNCA intentes hacer JOIN con tablas imaginarias llamadas `estados` o `tipos`."
        )
        
        # Si el prompt es una lista de diccionarios (formato Vanna)
        if isinstance(prompt, list):
            # Agregar la instrucción al último mensaje de usuario o al sistema
            if len(prompt) > 0 and prompt[-1]["role"] == "user":
                prompt[-1]["content"] += tenant_instruction
        elif isinstance(prompt, str):
            prompt += tenant_instruction
        
        try:
            forced_sql = self._build_forced_sql_from_prompt(prompt)
            if forced_sql:
                return forced_sql
            res = self.groq_client.chat.completions.create(
                model=self.model,
                messages=prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}],
                temperature=0.1, # Temperatura baja para código SQL más determinista
                max_tokens=1024,
            )
            llm_sql = res.choices[0].message.content
            return self._sanitize_sql(llm_sql)
        except Exception as e:
            print(f"Error en VannaAutomotrizService.submit_prompt: {str(e)}")
            raise e

    def _build_forced_sql_from_prompt(self, prompt) -> str:
        """
        SQL deterministico para intenciones criticas donde el LLM suele alucinar
        columnas o joins.
        """
        user_text = ""
        if isinstance(prompt, list):
            for item in reversed(prompt):
                if isinstance(item, dict) and item.get("role") == "user":
                    user_text = item.get("content", "")
                    break
        elif isinstance(prompt, str):
            user_text = prompt

        q = (user_text or "").lower()
        if ("plan de vehiculo" in q or "plan del vehiculo" in q) and "placa" in q:
            m = re.search(r"placa\s+([a-zA-Z0-9\-]+)", user_text, flags=re.IGNORECASE)
            if not m:
                return ""
            placa = m.group(1).strip().upper().replace("'", "''")
            return (
                "SELECT "
                "v.placa, v.marca, v.modelo, psv.estado AS estado_plan, "
                "COALESCE(sc.nombre, 'SIN_SERVICIO') AS servicio, "
                "psd.estado AS estado_servicio, psd.prioridad, "
                "psd.tiempo_estandar_min, psd.precio_referencial "
                "FROM vehiculos v "
                "JOIN planes_servicio_vehiculo psv ON psv.vehiculo_id = v.id "
                "LEFT JOIN planes_servicio_detalle psd ON psd.plan_servicio_id = psv.id "
                "LEFT JOIN servicios_catalogo sc ON sc.id = psd.servicio_catalogo_id "
                f"WHERE v.empresa_id = '{self.tenant_id}' AND v.placa = '{placa}' "
                "ORDER BY psd.prioridad NULLS LAST, sc.nombre NULLS LAST"
            )
        if ("pendientes a recibir" in q) or ("vehiculos pendientes a recibir" in q):
            return (
                "SELECT "
                "v.placa, v.marca, v.modelo, "
                "c.estado AS estado_cita, c.fecha_hora_inicio_programada AS programado, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente "
                "FROM citas c "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                "LEFT JOIN recepciones_vehiculo rv ON rv.cita_id = c.id "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "AND c.estado IN ('PROGRAMADA', 'EN_ESPERA_INGRESO') "
                "AND rv.id IS NULL "
                "ORDER BY c.fecha_hora_inicio_programada ASC"
            )
        if ("listos para ser recogidos" in q) or ("listos para recogida" in q) or ("pendientes de recogida" in q):
            return (
                "SELECT "
                "v.placa, v.marca, v.modelo, "
                "rv.fecha_recepcion, c.finalizada_at, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente "
                "FROM recepciones_vehiculo rv "
                "JOIN citas c ON c.id = rv.cita_id "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                f"WHERE rv.empresa_id = '{self.tenant_id}' "
                "AND rv.fecha_recogida IS NULL "
                "AND c.estado IN ('FINALIZADA', 'EN_PROCESO') "
                "ORDER BY rv.fecha_recepcion DESC"
            )
        if (
            ("citas pendientes" in q and "monto" in q)
            or ("citas pendientes" in q and "pagar" in q)
            or ("faltante" in q and "cita" in q)
            or ("saldo pendiente" in q and "cita" in q)
        ):
            return (
                "SELECT "
                "c.id AS cita_id, v.placa, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente, "
                "c.estado AS estado_cita, "
                "COALESCE(pc.total, 0) AS total_presupuesto, "
                "COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0) AS pagado, "
                "GREATEST(COALESCE(pc.total, 0) - COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0), 0) AS monto_faltante "
                "FROM citas c "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                "LEFT JOIN presupuestos_cita pc ON pc.cita_id = c.id "
                "LEFT JOIN pagos_taller pt ON pt.cita_id = c.id "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "AND c.estado IN ('PROGRAMADA', 'EN_ESPERA_INGRESO', 'EN_PROCESO', 'FINALIZADA') "
                "GROUP BY c.id, v.placa, u.nombres, u.apellidos, c.estado, pc.total "
                "HAVING GREATEST(COALESCE(pc.total, 0) - COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0), 0) > 0 "
                "ORDER BY monto_faltante DESC, v.placa ASC"
            )
        if (
            ("pagadas al 100" in q and "cita" in q)
            or ("citas pagadas" in q and "100" in q)
            or ("citas completamente pagadas" in q)
        ):
            return (
                "SELECT "
                "c.id AS cita_id, v.placa, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente, "
                "COALESCE(pc.total, 0) AS total_presupuesto, "
                "COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0) AS pagado "
                "FROM citas c "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                "LEFT JOIN presupuestos_cita pc ON pc.cita_id = c.id "
                "LEFT JOIN pagos_taller pt ON pt.cita_id = c.id "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "GROUP BY c.id, v.placa, u.nombres, u.apellidos, pc.total "
                "HAVING COALESCE(pc.total, 0) > 0 "
                "AND COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0) >= COALESCE(pc.total, 0) "
                "ORDER BY c.id DESC"
            )
        if (
            ("sin presupuesto" in q and "cita" in q)
            or ("citas sin presupuesto" in q)
            or ("citas que no tienen presupuesto" in q)
        ):
            return (
                "SELECT "
                "c.id AS cita_id, v.placa, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente, "
                "c.estado AS estado_cita, c.fecha_hora_inicio_programada AS programado "
                "FROM citas c "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                "LEFT JOIN presupuestos_cita pc ON pc.cita_id = c.id "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "AND pc.id IS NULL "
                "ORDER BY c.fecha_hora_inicio_programada DESC"
            )
        if (
            ("pago parcial" in q and "cita" in q)
            or ("citas con pago parcial" in q)
            or ("parcialmente pagadas" in q and "cita" in q)
        ):
            return (
                "SELECT "
                "c.id AS cita_id, v.placa, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente, "
                "COALESCE(pc.total, 0) AS total_presupuesto, "
                "COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0) AS pagado, "
                "GREATEST(COALESCE(pc.total, 0) - COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0), 0) AS saldo "
                "FROM citas c "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                "LEFT JOIN presupuestos_cita pc ON pc.cita_id = c.id "
                "LEFT JOIN pagos_taller pt ON pt.cita_id = c.id "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "GROUP BY c.id, v.placa, u.nombres, u.apellidos, pc.total "
                "HAVING COALESCE(pc.total, 0) > 0 "
                "AND COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0) > 0 "
                "AND COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado, 0) ELSE 0 END), 0) < COALESCE(pc.total, 0) "
                "ORDER BY saldo DESC"
            )
        if (
            ("sin pagos" in q and "cita" in q)
            or ("citas sin pagos" in q)
        ):
            return (
                "SELECT "
                "c.id AS cita_id, v.placa, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente, "
                "COALESCE(pc.total, 0) AS total_presupuesto "
                "FROM citas c "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                "LEFT JOIN presupuestos_cita pc ON pc.cita_id = c.id "
                "LEFT JOIN pagos_taller pt ON pt.cita_id = c.id AND pt.estado != 'ANULADO' "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "GROUP BY c.id, v.placa, u.nombres, u.apellidos, pc.total "
                "HAVING COUNT(pt.id) = 0 "
                "ORDER BY c.id DESC"
            )
        if (
            ("vencidas" in q and "cita" in q)
            or ("citas vencidas" in q)
            or ("atrasadas" in q and "cita" in q)
        ):
            return (
                "SELECT "
                "c.id AS cita_id, v.placa, "
                "u.nombres || ' ' || COALESCE(u.apellidos, '') AS cliente, "
                "c.estado AS estado_cita, c.fecha_hora_inicio_programada AS programado "
                "FROM citas c "
                "JOIN vehiculos v ON v.id = c.vehiculo_id "
                "LEFT JOIN usuarios u ON u.id = c.cliente_id "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "AND c.estado IN ('PROGRAMADA', 'EN_ESPERA_INGRESO', 'EN_PROCESO') "
                "AND c.fecha_hora_inicio_programada < NOW() "
                "ORDER BY c.fecha_hora_inicio_programada ASC"
            )
        # INVENTARIO: consultas directas frecuentes
        product_match = re.search(
            r"(?:producto|item|repuesto)\s+([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ\-\s]+)",
            user_text,
            flags=re.IGNORECASE,
        )
        product_name = (
            product_match.group(1).strip().replace("'", "''")
            if product_match
            else ""
        )
        if ("stock del producto" in q or "stock de" in q or "existencia de" in q) and product_name:
            return (
                "SELECT i.codigo, i.nombre, i.stock_actual, i.stock_minimo, i.unidad_medida "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true AND i.nombre ILIKE '%{product_name}%' "
                "ORDER BY i.nombre"
            )
        if ("precio del producto" in q or "precio de" in q or "cuanto cuesta" in q) and product_name:
            return (
                "SELECT i.codigo, i.nombre, i.precio_venta, i.costo_promedio, "
                "(i.precio_venta - i.costo_promedio) AS margen_unitario "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true AND i.nombre ILIKE '%{product_name}%' "
                "ORDER BY i.nombre"
            )
        if ("costo del producto" in q or "costo de" in q) and product_name:
            return (
                "SELECT i.codigo, i.nombre, i.costo_promedio, i.precio_venta "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true AND i.nombre ILIKE '%{product_name}%' "
                "ORDER BY i.nombre"
            )
        if ("detalle del producto" in q or "informacion del producto" in q or "datos del producto" in q) and product_name:
            return (
                "SELECT i.codigo, i.nombre, i.descripcion, i.tipo_item, i.unidad_medida, "
                "i.stock_actual, i.stock_minimo, i.costo_promedio, i.precio_venta, c.nombre AS categoria "
                "FROM items_inventario i "
                "LEFT JOIN categorias_inventario c ON c.id = i.categoria_id "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.nombre ILIKE '%{product_name}%' "
                "ORDER BY i.nombre"
            )
        if ("productos con stock bajo" in q or "stock bajo" in q or "por agotarse" in q):
            return (
                "SELECT i.codigo, i.nombre, i.stock_actual, i.stock_minimo, "
                "(i.stock_minimo - i.stock_actual) AS deficit, c.nombre AS categoria "
                "FROM items_inventario i "
                "LEFT JOIN categorias_inventario c ON c.id = i.categoria_id "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true AND i.stock_actual <= i.stock_minimo "
                "ORDER BY deficit DESC, i.stock_actual ASC"
            )
        if ("sin stock" in q or "agotados" in q or "stock en cero" in q):
            return (
                "SELECT i.codigo, i.nombre, i.stock_actual, i.stock_minimo, c.nombre AS categoria "
                "FROM items_inventario i "
                "LEFT JOIN categorias_inventario c ON c.id = i.categoria_id "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true AND i.stock_actual <= 0 "
                "ORDER BY i.nombre"
            )
        if ("top productos con mayor stock" in q or "mas stock" in q):
            return (
                "SELECT i.codigo, i.nombre, i.stock_actual, i.unidad_medida "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true "
                "ORDER BY i.stock_actual DESC, i.nombre ASC LIMIT 20"
            )
        if ("top productos con menor stock" in q or "menos stock" in q):
            return (
                "SELECT i.codigo, i.nombre, i.stock_actual, i.stock_minimo "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true "
                "ORDER BY i.stock_actual ASC, i.nombre ASC LIMIT 20"
            )
        if ("valor total de inventario" in q or "valorizacion de inventario" in q or "cuanto vale el inventario" in q):
            return (
                "SELECT "
                "COALESCE(SUM(i.stock_actual * i.costo_promedio), 0) AS valor_costo, "
                "COALESCE(SUM(i.stock_actual * i.precio_venta), 0) AS valor_venta "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true"
            )
        if ("margen" in q and "inventario" in q):
            return (
                "SELECT i.codigo, i.nombre, i.costo_promedio, i.precio_venta, "
                "(i.precio_venta - i.costo_promedio) AS margen_unitario, "
                "CASE WHEN i.costo_promedio > 0 THEN ROUND(((i.precio_venta - i.costo_promedio) / i.costo_promedio) * 100, 2) ELSE NULL END AS margen_pct "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true "
                "ORDER BY margen_unitario DESC, i.nombre ASC LIMIT 30"
            )
        if ("inventario por categoria" in q or "stock por categoria" in q):
            return (
                "SELECT COALESCE(c.nombre, 'SIN_CATEGORIA') AS categoria, "
                "COUNT(i.id) AS items, COALESCE(SUM(i.stock_actual), 0) AS stock_total "
                "FROM items_inventario i "
                "LEFT JOIN categorias_inventario c ON c.id = i.categoria_id "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true "
                "GROUP BY COALESCE(c.nombre, 'SIN_CATEGORIA') "
                "ORDER BY stock_total DESC"
            )
        if ("productos mas caros" in q or "precio mas alto" in q):
            return (
                "SELECT i.codigo, i.nombre, i.precio_venta, i.costo_promedio "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true "
                "ORDER BY i.precio_venta DESC, i.nombre ASC LIMIT 20"
            )
        if ("productos mas baratos" in q or "precio mas bajo" in q):
            return (
                "SELECT i.codigo, i.nombre, i.precio_venta, i.costo_promedio "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true "
                "ORDER BY i.precio_venta ASC, i.nombre ASC LIMIT 20"
            )
        if ("compras recientes" in q or "ultimas compras" in q):
            return (
                "SELECT c.numero_documento, c.fecha_compra, c.estado, c.total "
                "FROM compras c "
                f"WHERE c.empresa_id = '{self.tenant_id}' "
                "ORDER BY c.fecha_compra DESC LIMIT 20"
            )
        if ("productos mas comprados" in q or "repuestos mas comprados" in q):
            return (
                "SELECT i.nombre, COALESCE(SUM(cd.cantidad), 0) AS cantidad_comprada, "
                "COALESCE(SUM(cd.subtotal), 0) AS monto_comprado "
                "FROM compras_detalle cd "
                "JOIN compras c ON c.id = cd.compra_id "
                "LEFT JOIN items_inventario i ON i.id = cd.item_inventario_id "
                f"WHERE cd.empresa_id = '{self.tenant_id}' AND c.estado = 'CONFIRMADA' "
                "GROUP BY i.nombre "
                "ORDER BY cantidad_comprada DESC NULLS LAST LIMIT 20"
            )
        if ("ventas recientes" in q or "ultimas ventas" in q):
            return (
                "SELECT v.id AS venta_id, v.created_at, v.estado, v.total "
                "FROM ventas_mostrador v "
                f"WHERE v.empresa_id = '{self.tenant_id}' "
                "ORDER BY v.created_at DESC LIMIT 20"
            )
        if ("productos mas vendidos" in q or "repuestos mas vendidos" in q):
            return (
                "SELECT i.nombre, COALESCE(SUM(vd.cantidad), 0) AS cantidad_vendida, "
                "COALESCE(SUM(vd.subtotal), 0) AS monto_vendido "
                "FROM ventas_mostrador_detalle vd "
                "JOIN ventas_mostrador v ON v.id = vd.venta_id "
                "LEFT JOIN items_inventario i ON i.id = vd.item_inventario_id "
                f"WHERE vd.empresa_id = '{self.tenant_id}' AND v.estado = 'CONFIRMADA' "
                "GROUP BY i.nombre "
                "ORDER BY cantidad_vendida DESC NULLS LAST LIMIT 20"
            )
        if ("rotacion de inventario" in q or "rotacion por producto" in q):
            return (
                "SELECT i.nombre, "
                "COALESCE(SUM(vd.cantidad), 0) AS salidas_ventas, "
                "COALESCE(i.stock_actual, 0) AS stock_actual "
                "FROM items_inventario i "
                "LEFT JOIN ventas_mostrador_detalle vd ON vd.item_inventario_id = i.id "
                "LEFT JOIN ventas_mostrador v ON v.id = vd.venta_id AND v.estado = 'CONFIRMADA' "
                f"WHERE i.empresa_id = '{self.tenant_id}' "
                "GROUP BY i.id, i.nombre, i.stock_actual "
                "ORDER BY salidas_ventas DESC, i.nombre ASC LIMIT 30"
            )
        if ("buscar producto" in q or "encontrar producto" in q) and product_name:
            return (
                "SELECT i.codigo, i.nombre, i.tipo_item, i.stock_actual, i.precio_venta "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.nombre ILIKE '%{product_name}%' "
                "ORDER BY i.nombre"
            )
        if ("lista de productos" in q or "listar productos" in q or "inventario completo" in q):
            return (
                "SELECT i.codigo, i.nombre, i.tipo_item, i.stock_actual, i.stock_minimo, i.precio_venta, i.costo_promedio "
                "FROM items_inventario i "
                f"WHERE i.empresa_id = '{self.tenant_id}' AND i.activo = true "
                "ORDER BY i.nombre"
            )
        # ESPACIOS Y HORARIOS (15+ intenciones)
        if ("espacios de trabajo y sus horarios" in q) or ("espacios de trabajo" in q and "horarios" in q):
            return (
                "SELECT e.codigo, e.nombre, e.tipo, e.estado, "
                "h.dia_semana, h.hora_inicio, h.hora_fin, h.activo AS horario_activo "
                "FROM espacios_trabajo e "
                "LEFT JOIN horarios_espacios_trabajo h ON h.espacio_trabajo_id = e.id "
                f"WHERE e.empresa_id = '{self.tenant_id}' "
                "ORDER BY e.tipo, e.nombre, h.dia_semana, h.hora_inicio"
            )
        if ("espacios disponibles" in q) or ("espacios libres" in q):
            return (
                "SELECT e.codigo, e.nombre, e.tipo, e.estado "
                "FROM espacios_trabajo e "
                f"WHERE e.empresa_id = '{self.tenant_id}' AND e.activo = true AND e.estado = 'DISPONIBLE' "
                "ORDER BY e.tipo, e.nombre"
            )
        if ("espacios ocupados" in q):
            return (
                "SELECT e.codigo, e.nombre, e.tipo, e.estado "
                "FROM espacios_trabajo e "
                f"WHERE e.empresa_id = '{self.tenant_id}' AND e.activo = true AND e.estado = 'OCUPADO' "
                "ORDER BY e.tipo, e.nombre"
            )
        if ("espacios en mantenimiento" in q):
            return (
                "SELECT e.codigo, e.nombre, e.tipo, e.estado, e.observaciones "
                "FROM espacios_trabajo e "
                f"WHERE e.empresa_id = '{self.tenant_id}' AND e.estado = 'MANTENIMIENTO' "
                "ORDER BY e.nombre"
            )
        if ("espacios por tipo" in q):
            return (
                "SELECT e.tipo, COUNT(*) AS total "
                "FROM espacios_trabajo e "
                f"WHERE e.empresa_id = '{self.tenant_id}' AND e.activo = true "
                "GROUP BY e.tipo "
                "ORDER BY total DESC"
            )
        if ("estado de los espacios" in q) or ("resumen de espacios" in q):
            return (
                "SELECT e.estado, COUNT(*) AS total "
                "FROM espacios_trabajo e "
                f"WHERE e.empresa_id = '{self.tenant_id}' "
                "GROUP BY e.estado "
                "ORDER BY total DESC"
            )
        if ("horarios por dia" in q) or ("horarios del dia" in q):
            return (
                "SELECT h.dia_semana, e.nombre AS espacio, h.hora_inicio, h.hora_fin "
                "FROM horarios_espacios_trabajo h "
                "JOIN espacios_trabajo e ON e.id = h.espacio_trabajo_id "
                f"WHERE h.empresa_id = '{self.tenant_id}' AND h.activo = true "
                "ORDER BY h.dia_semana, h.hora_inicio, e.nombre"
            )
        if ("horarios activos" in q):
            return (
                "SELECT e.nombre AS espacio, h.dia_semana, h.hora_inicio, h.hora_fin "
                "FROM horarios_espacios_trabajo h "
                "JOIN espacios_trabajo e ON e.id = h.espacio_trabajo_id "
                f"WHERE h.empresa_id = '{self.tenant_id}' AND h.activo = true "
                "ORDER BY e.nombre, h.dia_semana, h.hora_inicio"
            )
        if ("horarios inactivos" in q):
            return (
                "SELECT e.nombre AS espacio, h.dia_semana, h.hora_inicio, h.hora_fin "
                "FROM horarios_espacios_trabajo h "
                "JOIN espacios_trabajo e ON e.id = h.espacio_trabajo_id "
                f"WHERE h.empresa_id = '{self.tenant_id}' AND h.activo = false "
                "ORDER BY e.nombre, h.dia_semana, h.hora_inicio"
            )
        if ("carga por espacio" in q) or ("citas por espacio" in q):
            return (
                "SELECT e.nombre AS espacio, COUNT(DISTINCT ces.cita_id) AS citas_asignadas "
                "FROM espacios_trabajo e "
                "LEFT JOIN citas_espacios_segmentos ces ON ces.espacio_trabajo_id = e.id "
                f"WHERE e.empresa_id = '{self.tenant_id}' "
                "GROUP BY e.nombre "
                "ORDER BY citas_asignadas DESC, e.nombre"
            )
        if ("espacios mas usados" in q):
            return (
                "SELECT e.nombre AS espacio, e.tipo, COUNT(*) AS segmentos "
                "FROM citas_espacios_segmentos ces "
                "JOIN espacios_trabajo e ON e.id = ces.espacio_trabajo_id "
                f"WHERE ces.empresa_id = '{self.tenant_id}' "
                "GROUP BY e.nombre, e.tipo "
                "ORDER BY segmentos DESC LIMIT 20"
            )
        if ("agenda de espacios" in q) or ("programacion de espacios" in q):
            return (
                "SELECT e.nombre AS espacio, ces.tipo_segmento, ces.estado_segmento, "
                "ces.inicio_programado, ces.fin_programado "
                "FROM citas_espacios_segmentos ces "
                "JOIN espacios_trabajo e ON e.id = ces.espacio_trabajo_id "
                f"WHERE ces.empresa_id = '{self.tenant_id}' "
                "ORDER BY ces.inicio_programado DESC LIMIT 100"
            )
        if ("espacios con conflictos" in q) or ("solapados" in q):
            return (
                "SELECT e.nombre AS espacio, ces1.cita_id AS cita_a, ces2.cita_id AS cita_b, "
                "ces1.inicio_programado, ces1.fin_programado, ces2.inicio_programado AS inicio_b, ces2.fin_programado AS fin_b "
                "FROM citas_espacios_segmentos ces1 "
                "JOIN citas_espacios_segmentos ces2 ON ces1.espacio_trabajo_id = ces2.espacio_trabajo_id AND ces1.id <> ces2.id "
                "JOIN espacios_trabajo e ON e.id = ces1.espacio_trabajo_id "
                f"WHERE ces1.empresa_id = '{self.tenant_id}' "
                "AND ces1.inicio_programado < ces2.fin_programado "
                "AND ces2.inicio_programado < ces1.fin_programado "
                "ORDER BY e.nombre, ces1.inicio_programado LIMIT 50"
            )
        if ("tiempo ocupado por espacio" in q):
            return (
                "SELECT e.nombre AS espacio, "
                "COALESCE(SUM(EXTRACT(EPOCH FROM (COALESCE(ces.fin_real, ces.fin_programado) - COALESCE(ces.inicio_real, ces.inicio_programado))))/60, 0) AS minutos_ocupados "
                "FROM espacios_trabajo e "
                "LEFT JOIN citas_espacios_segmentos ces ON ces.espacio_trabajo_id = e.id "
                f"WHERE e.empresa_id = '{self.tenant_id}' "
                "GROUP BY e.nombre "
                "ORDER BY minutos_ocupados DESC"
            )
        if ("horario de atencion de" in q) or ("horario del espacio" in q):
            space_match = re.search(r"(?:de|del espacio)\s+([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ_\-\s]+)", user_text, flags=re.IGNORECASE)
            space_name = space_match.group(1).strip().replace("'", "''") if space_match else ""
            if space_name:
                return (
                    "SELECT e.codigo, e.nombre, h.dia_semana, h.hora_inicio, h.hora_fin, h.activo "
                    "FROM espacios_trabajo e "
                    "LEFT JOIN horarios_espacios_trabajo h ON h.espacio_trabajo_id = e.id "
                    f"WHERE e.empresa_id = '{self.tenant_id}' AND e.nombre ILIKE '%{space_name}%' "
                    "ORDER BY h.dia_semana, h.hora_inicio"
                )
        if ("espacios sin horario" in q):
            return (
                "SELECT e.codigo, e.nombre, e.tipo, e.estado "
                "FROM espacios_trabajo e "
                "LEFT JOIN horarios_espacios_trabajo h ON h.espacio_trabajo_id = e.id "
                f"WHERE e.empresa_id = '{self.tenant_id}' "
                "GROUP BY e.id, e.codigo, e.nombre, e.tipo, e.estado "
                "HAVING COUNT(h.id) = 0 "
                "ORDER BY e.nombre"
            )
        if ("espacios con mayor disponibilidad" in q):
            return (
                "SELECT e.nombre AS espacio, COUNT(h.id) AS bloques_horarios "
                "FROM espacios_trabajo e "
                "LEFT JOIN horarios_espacios_trabajo h ON h.espacio_trabajo_id = e.id AND h.activo = true "
                f"WHERE e.empresa_id = '{self.tenant_id}' "
                "GROUP BY e.nombre "
                "ORDER BY bloques_horarios DESC, e.nombre"
            )
        # ORDENES DE TRABAJO (15+)
        if ("ordenes de trabajo abiertas" in q) or ("ot abiertas" in q):
            return ("SELECT og.numero, og.estado, og.fecha_apertura, v.placa, u.nombres || ' ' || COALESCE(u.apellidos,'') AS cliente "
                    "FROM ordenes_trabajo_global og JOIN citas c ON c.id = og.cita_id "
                    "LEFT JOIN vehiculos v ON v.id = c.vehiculo_id LEFT JOIN usuarios u ON u.id = c.cliente_id "
                    f"WHERE og.empresa_id = '{self.tenant_id}' AND og.estado IN ('ABIERTA','ASIGNADA') ORDER BY og.fecha_apertura DESC")
        if ("ordenes en proceso" in q) or ("ot en proceso" in q):
            return f"SELECT numero, estado, fecha_apertura FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' AND estado = 'EN_PROCESO' ORDER BY fecha_apertura DESC"
        if ("ordenes finalizadas" in q) or ("ot finalizadas" in q):
            return f"SELECT numero, estado, fecha_cierre FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' AND estado IN ('FINALIZADA','CERRADA') ORDER BY fecha_cierre DESC NULLS LAST"
        if ("detalle de orden" in q) or ("servicios de la orden" in q):
            return ("SELECT og.numero, sc.nombre AS servicio, od.estado, od.prioridad, od.tiempo_estandar_min, od.tiempo_real_min "
                    "FROM ordenes_trabajo_detalle od JOIN ordenes_trabajo_global og ON og.id = od.orden_global_id "
                    "LEFT JOIN servicios_catalogo sc ON sc.id = od.servicio_catalogo_id "
                    f"WHERE od.empresa_id = '{self.tenant_id}' ORDER BY og.numero DESC, od.orden_visual ASC LIMIT 200")
        if ("ordenes por mecanico" in q) or ("carga de mecanicos" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS mecanico, COUNT(od.id) AS servicios_asignados "
                    "FROM ordenes_trabajo_detalle od LEFT JOIN usuarios u ON u.id = od.mecanico_asignado_id "
                    f"WHERE od.empresa_id = '{self.tenant_id}' GROUP BY u.nombres, u.apellidos ORDER BY servicios_asignados DESC")
        if ("ot pausadas" in q) or ("ordenes pausadas" in q):
            return f"SELECT numero, estado, fecha_apertura FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' AND estado = 'PAUSADA' ORDER BY fecha_apertura DESC"
        if ("ordenes canceladas" in q):
            return f"SELECT numero, estado, fecha_apertura FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' AND estado = 'CANCELADA' ORDER BY fecha_apertura DESC"
        if ("top servicios de orden" in q) or ("servicios mas ejecutados en ordenes" in q):
            return ("SELECT sc.nombre, COUNT(od.id) AS veces "
                    "FROM ordenes_trabajo_detalle od LEFT JOIN servicios_catalogo sc ON sc.id = od.servicio_catalogo_id "
                    f"WHERE od.empresa_id = '{self.tenant_id}' GROUP BY sc.nombre ORDER BY veces DESC LIMIT 20")
        if ("eficiencia mecanicos" in q) or ("mecanicos mas eficientes" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS mecanico, "
                    "COUNT(od.id) FILTER (WHERE od.estado='FINALIZADO') AS finalizados, "
                    "AVG(od.tiempo_real_min) AS promedio_tiempo_real "
                    "FROM ordenes_trabajo_detalle od LEFT JOIN usuarios u ON u.id = od.mecanico_asignado_id "
                    f"WHERE od.empresa_id = '{self.tenant_id}' GROUP BY u.nombres, u.apellidos ORDER BY finalizados DESC")
        if ("ordenes por estado" in q):
            return f"SELECT estado, COUNT(*) AS total FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' GROUP BY estado ORDER BY total DESC"
        if ("ordenes de hoy" in q):
            return f"SELECT numero, estado, fecha_apertura FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' AND DATE(fecha_apertura)=CURRENT_DATE ORDER BY fecha_apertura DESC"
        if ("ordenes de esta semana" in q):
            return f"SELECT numero, estado, fecha_apertura FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' AND fecha_apertura >= date_trunc('week', now()) ORDER BY fecha_apertura DESC"
        if ("ordenes de este mes" in q):
            return f"SELECT numero, estado, fecha_apertura FROM ordenes_trabajo_global WHERE empresa_id = '{self.tenant_id}' AND fecha_apertura >= date_trunc('month', now()) ORDER BY fecha_apertura DESC"
        if ("ordenes sin mecanico" in q):
            return f"SELECT og.numero, od.id AS detalle_id, od.estado FROM ordenes_trabajo_detalle od JOIN ordenes_trabajo_global og ON og.id=od.orden_global_id WHERE od.empresa_id = '{self.tenant_id}' AND od.mecanico_asignado_id IS NULL ORDER BY og.numero DESC"
        if ("ordenes atrasadas" in q):
            return ("SELECT og.numero, og.estado, c.fecha_hora_fin_programada "
                    "FROM ordenes_trabajo_global og JOIN citas c ON c.id = og.cita_id "
                    f"WHERE og.empresa_id = '{self.tenant_id}' AND og.estado IN ('ABIERTA','ASIGNADA','EN_PROCESO') AND c.fecha_hora_fin_programada < NOW() ORDER BY c.fecha_hora_fin_programada ASC")
        # CITAS (15+)
        if ("citas de hoy" in q):
            return f"SELECT id, estado, fecha_hora_inicio_programada, fecha_hora_fin_programada FROM citas WHERE empresa_id = '{self.tenant_id}' AND DATE(fecha_hora_inicio_programada)=CURRENT_DATE ORDER BY fecha_hora_inicio_programada"
        if ("citas de esta semana" in q):
            return f"SELECT id, estado, fecha_hora_inicio_programada FROM citas WHERE empresa_id = '{self.tenant_id}' AND fecha_hora_inicio_programada >= date_trunc('week', now()) ORDER BY fecha_hora_inicio_programada"
        if ("citas de este mes" in q):
            return f"SELECT id, estado, fecha_hora_inicio_programada FROM citas WHERE empresa_id = '{self.tenant_id}' AND fecha_hora_inicio_programada >= date_trunc('month', now()) ORDER BY fecha_hora_inicio_programada"
        if ("citas por estado" in q):
            return f"SELECT estado, COUNT(*) AS total FROM citas WHERE empresa_id = '{self.tenant_id}' GROUP BY estado ORDER BY total DESC"
        if ("citas canceladas" in q):
            return f"SELECT id, motivo_cancelacion, fecha_hora_inicio_programada FROM citas WHERE empresa_id = '{self.tenant_id}' AND estado='CANCELADA' ORDER BY fecha_hora_inicio_programada DESC"
        if ("citas no show" in q):
            return f"SELECT id, fecha_hora_inicio_programada, no_show_marcado_at FROM citas WHERE empresa_id = '{self.tenant_id}' AND estado='NO_SHOW' ORDER BY no_show_marcado_at DESC"
        if ("citas reprogramadas" in q):
            return f"SELECT id, reprogramaciones_count, ultima_reprogramacion_at, motivo_ultima_reprogramacion FROM citas WHERE empresa_id = '{self.tenant_id}' AND reprogramaciones_count > 0 ORDER BY reprogramaciones_count DESC"
        if ("tiempo promedio de cita" in q):
            return f"SELECT AVG(duracion_estimada_min) AS duracion_promedio_min FROM citas WHERE empresa_id = '{self.tenant_id}'"
        if ("citas por canal" in q):
            return f"SELECT canal_origen, COUNT(*) AS total FROM citas WHERE empresa_id = '{self.tenant_id}' GROUP BY canal_origen ORDER BY total DESC"
        if ("citas finalizadas" in q):
            return f"SELECT id, finalizada_at, vehiculo_devuelto_at FROM citas WHERE empresa_id = '{self.tenant_id}' AND estado='FINALIZADA' ORDER BY finalizada_at DESC NULLS LAST"
        if ("citas en espera de ingreso" in q):
            return f"SELECT id, fecha_hora_inicio_programada FROM citas WHERE empresa_id = '{self.tenant_id}' AND estado='EN_ESPERA_INGRESO' ORDER BY fecha_hora_inicio_programada"
        if ("citas programadas" in q):
            return f"SELECT id, fecha_hora_inicio_programada, fecha_hora_fin_programada FROM citas WHERE empresa_id = '{self.tenant_id}' AND estado='PROGRAMADA' ORDER BY fecha_hora_inicio_programada"
        if ("citas con recepcion" in q):
            return ("SELECT c.id, rv.fecha_recepcion, rv.kilometraje_ingreso "
                    "FROM citas c JOIN recepciones_vehiculo rv ON rv.cita_id = c.id "
                    f"WHERE c.empresa_id = '{self.tenant_id}' ORDER BY rv.fecha_recepcion DESC")
        if ("citas sin recepcion" in q):
            return ("SELECT c.id, c.estado, c.fecha_hora_inicio_programada "
                    "FROM citas c LEFT JOIN recepciones_vehiculo rv ON rv.cita_id = c.id "
                    f"WHERE c.empresa_id = '{self.tenant_id}' AND rv.id IS NULL ORDER BY c.fecha_hora_inicio_programada DESC")
        if ("top clientes por citas" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS cliente, COUNT(c.id) AS total_citas "
                    "FROM citas c JOIN usuarios u ON u.id = c.cliente_id "
                    f"WHERE c.empresa_id = '{self.tenant_id}' GROUP BY u.nombres,u.apellidos ORDER BY total_citas DESC LIMIT 20")
        # VEHICULOS Y USUARIOS (15+)
        if ("vehiculos por cliente" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS cliente, COUNT(v.id) AS vehiculos "
                    "FROM vehiculos v JOIN usuarios u ON u.id = v.propietario_id "
                    f"WHERE v.empresa_id = '{self.tenant_id}' GROUP BY u.nombres,u.apellidos ORDER BY vehiculos DESC")
        if ("clientes con mas vehiculos" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS cliente, COUNT(v.id) AS total "
                    "FROM vehiculos v JOIN usuarios u ON u.id = v.propietario_id "
                    f"WHERE v.empresa_id = '{self.tenant_id}' GROUP BY u.nombres,u.apellidos ORDER BY total DESC LIMIT 20")
        if ("vehiculos activos" in q):
            return f"SELECT placa, marca, modelo, estado FROM vehiculos WHERE empresa_id = '{self.tenant_id}' AND estado='ACTIVO' ORDER BY placa"
        if ("vehiculos inactivos" in q):
            return f"SELECT placa, marca, modelo, estado FROM vehiculos WHERE empresa_id = '{self.tenant_id}' AND estado='INACTIVO' ORDER BY placa"
        if ("vehiculos por marca" in q):
            return f"SELECT marca, COUNT(*) AS total FROM vehiculos WHERE empresa_id = '{self.tenant_id}' GROUP BY marca ORDER BY total DESC"
        if ("vehiculos por modelo" in q):
            return f"SELECT modelo, COUNT(*) AS total FROM vehiculos WHERE empresa_id = '{self.tenant_id}' GROUP BY modelo ORDER BY total DESC"
        if ("vehiculos por anio" in q) or ("vehiculos por año" in q):
            return f"SELECT anio, COUNT(*) AS total FROM vehiculos WHERE empresa_id = '{self.tenant_id}' GROUP BY anio ORDER BY anio DESC"
        if ("usuarios por rol" in q):
            return ("SELECT r.nombre AS rol, COUNT(u.id) AS total "
                    "FROM usuarios u LEFT JOIN roles r ON r.id = u.rol_id "
                    f"WHERE u.empresa_id = '{self.tenant_id}' GROUP BY r.nombre ORDER BY total DESC")
        # Consultas directas por rol (evitar mezcla con citas/vehículos)
        if ("asesores de servicio" in q) or ("asesores" in q and "servicio" in q):
            return ("SELECT u.nombres, u.apellidos, u.email, u.telefono, r.nombre AS rol "
                    "FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                    f"WHERE u.empresa_id = '{self.tenant_id}' AND u.is_active = true "
                    "AND (r.nombre ILIKE '%ASESOR%' OR r.nombre ILIKE '%SERVICIO%') "
                    "ORDER BY u.nombres, u.apellidos")
        if ("todos los mecanicos" in q) or ("mecanicos" in q and "usuarios" in q) or ("lista de mecanicos" in q):
            return ("SELECT u.nombres, u.apellidos, u.email, u.telefono, r.nombre AS rol "
                    "FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                    f"WHERE u.empresa_id = '{self.tenant_id}' AND u.is_active = true "
                    "AND r.nombre ILIKE '%MECANIC%' "
                    "ORDER BY u.nombres, u.apellidos")
        if ("todos los admins" in q) or ("administradores" in q) or ("usuarios admin" in q):
            return ("SELECT u.nombres, u.apellidos, u.email, u.telefono, r.nombre AS rol "
                    "FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                    f"WHERE u.empresa_id = '{self.tenant_id}' AND u.is_active = true "
                    "AND (r.nombre ILIKE '%ADMIN%' OR u.is_staff = true) "
                    "ORDER BY u.nombres, u.apellidos")
        if ("todos los clientes" in q) or ("usuarios clientes" in q):
            return ("SELECT u.nombres, u.apellidos, u.email, u.telefono, r.nombre AS rol "
                    "FROM usuarios u LEFT JOIN roles r ON r.id = u.rol_id "
                    f"WHERE u.empresa_id = '{self.tenant_id}' AND u.is_active = true "
                    "AND r.nombre ILIKE '%CLIENTE%' "
                    "ORDER BY u.nombres, u.apellidos")
        if ("usuarios del rol" in q) or ("usuarios con rol" in q):
            rm = re.search(r"(?:rol|con rol)\s+([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ_\\-\\s]+)", user_text, flags=re.IGNORECASE)
            role_name = rm.group(1).strip().replace("'", "''") if rm else ""
            if role_name:
                return ("SELECT u.nombres, u.apellidos, u.email, u.telefono, r.nombre AS rol "
                        "FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                        f"WHERE u.empresa_id = '{self.tenant_id}' AND r.nombre ILIKE '%{role_name}%' "
                        "ORDER BY u.nombres, u.apellidos")
        if ("usuarios inactivos" in q):
            return f"SELECT nombres, apellidos, email FROM usuarios WHERE empresa_id = '{self.tenant_id}' AND is_active = false ORDER BY nombres"
        if ("usuarios activos" in q):
            return f"SELECT nombres, apellidos, email FROM usuarios WHERE empresa_id = '{self.tenant_id}' AND is_active = true ORDER BY nombres"
        if ("vehiculos sin citas" in q):
            return ("SELECT v.placa, v.marca, v.modelo FROM vehiculos v "
                    "LEFT JOIN citas c ON c.vehiculo_id = v.id "
                    f"WHERE v.empresa_id = '{self.tenant_id}' GROUP BY v.id, v.placa, v.marca, v.modelo HAVING COUNT(c.id)=0 ORDER BY v.placa")
        if ("vehiculos con mas citas" in q):
            return ("SELECT v.placa, v.marca, v.modelo, COUNT(c.id) AS total_citas "
                    "FROM vehiculos v LEFT JOIN citas c ON c.vehiculo_id = v.id "
                    f"WHERE v.empresa_id = '{self.tenant_id}' GROUP BY v.id, v.placa, v.marca, v.modelo ORDER BY total_citas DESC LIMIT 20")
        if ("usuarios nuevos" in q):
            return f"SELECT nombres, apellidos, email, created_at FROM usuarios WHERE empresa_id = '{self.tenant_id}' ORDER BY created_at DESC LIMIT 50"
        if ("vehiculos nuevos" in q):
            return f"SELECT placa, marca, modelo, created_at FROM vehiculos WHERE empresa_id = '{self.tenant_id}' ORDER BY created_at DESC LIMIT 50"
        if ("usuarios con telefono" in q):
            return f"SELECT nombres, apellidos, telefono FROM usuarios WHERE empresa_id = '{self.tenant_id}' AND COALESCE(telefono,'') <> '' ORDER BY nombres"
        # FINANCIERO (15+)
        if ("ventas del dia de hoy" in q) or ("ventas de hoy" in q):
            return f"SELECT COALESCE(SUM(total),0) AS ventas_hoy FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' AND estado='CONFIRMADA' AND DATE(created_at)=CURRENT_DATE"
        if ("ingresos del dia" in q):
            return f"SELECT COALESCE(SUM(total),0) AS ingresos_dia FROM facturas WHERE empresa_id = '{self.tenant_id}' AND DATE(fecha_emision)=CURRENT_DATE"
        if ("ingresos de la semana" in q):
            return f"SELECT COALESCE(SUM(total),0) AS ingresos_semana FROM facturas WHERE empresa_id = '{self.tenant_id}' AND fecha_emision >= date_trunc('week', now())"
        if ("ingresos del mes" in q):
            return f"SELECT COALESCE(SUM(total),0) AS ingresos_mes FROM facturas WHERE empresa_id = '{self.tenant_id}' AND fecha_emision >= date_trunc('month', now())"
        if ("ingresos del año" in q) or ("ingresos del ano" in q):
            return f"SELECT COALESCE(SUM(total),0) AS ingresos_anio FROM facturas WHERE empresa_id = '{self.tenant_id}' AND fecha_emision >= date_trunc('year', now())"
        if ("ultimos 3 dias" in q and "ingresos" in q):
            return f"SELECT DATE(fecha_emision) AS dia, COALESCE(SUM(total),0) AS ingresos FROM facturas WHERE empresa_id = '{self.tenant_id}' AND fecha_emision >= CURRENT_DATE - INTERVAL '2 day' GROUP BY DATE(fecha_emision) ORDER BY dia"
        if ("ingresos pendientes" in q) or ("cosas a pagar" in q) or ("pendiente de pago" in q):
            return ("SELECT c.id AS cita_id, v.placa, COALESCE(pc.total,0) AS presupuesto_total, "
                    "COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado,0) ELSE 0 END),0) AS pagado, "
                    "GREATEST(COALESCE(pc.total,0)-COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado,0) ELSE 0 END),0),0) AS pendiente "
                    "FROM citas c JOIN vehiculos v ON v.id=c.vehiculo_id LEFT JOIN presupuestos_cita pc ON pc.cita_id=c.id LEFT JOIN pagos_taller pt ON pt.cita_id=c.id "
                    f"WHERE c.empresa_id = '{self.tenant_id}' GROUP BY c.id,v.placa,pc.total HAVING GREATEST(COALESCE(pc.total,0)-COALESCE(SUM(CASE WHEN pt.estado != 'ANULADO' THEN COALESCE(pt.monto_pagado,0) ELSE 0 END),0),0) > 0 ORDER BY pendiente DESC")
        if ("ticket promedio" in q):
            return f"SELECT COALESCE(SUM(monto_total),0) / NULLIF(COUNT(DISTINCT cita_id),0) AS ticket_promedio FROM pagos_taller WHERE empresa_id = '{self.tenant_id}' AND estado != 'ANULADO'"
        if ("margen de ventas" in q):
            return ("SELECT COALESCE(SUM(vd.subtotal),0) AS ingresos_ventas, "
                    "COALESCE(SUM(vd.cantidad * i.costo_promedio),0) AS costo_estimado, "
                    "COALESCE(SUM(vd.subtotal),0)-COALESCE(SUM(vd.cantidad * i.costo_promedio),0) AS margen "
                    "FROM ventas_mostrador_detalle vd LEFT JOIN items_inventario i ON i.id = vd.item_inventario_id "
                    f"WHERE vd.empresa_id = '{self.tenant_id}'")
        if ("facturas emitidas hoy" in q):
            return f"SELECT numero, fecha_emision, total FROM facturas WHERE empresa_id = '{self.tenant_id}' AND DATE(fecha_emision)=CURRENT_DATE ORDER BY fecha_emision DESC"
        if ("facturas de esta semana" in q):
            return f"SELECT numero, fecha_emision, total FROM facturas WHERE empresa_id = '{self.tenant_id}' AND fecha_emision >= date_trunc('week', now()) ORDER BY fecha_emision DESC"
        if ("facturas de este mes" in q):
            return f"SELECT numero, fecha_emision, total FROM facturas WHERE empresa_id = '{self.tenant_id}' AND fecha_emision >= date_trunc('month', now()) ORDER BY fecha_emision DESC"
        if ("pagos fallidos" in q):
            return f"SELECT codigo_pago, estado, monto_total, created_at FROM pagos_taller WHERE empresa_id = '{self.tenant_id}' AND estado IN ('FALLIDO','RECHAZADO','ERROR') ORDER BY created_at DESC"
        if ("pagos confirmados" in q):
            return f"SELECT codigo_pago, estado, monto_pagado, fecha_pago FROM pagos_taller WHERE empresa_id = '{self.tenant_id}' AND estado IN ('CONFIRMADO','FACTURADO','RECIBIDO') ORDER BY fecha_pago DESC NULLS LAST"
        if ("ingresos por dia" in q):
            return f"SELECT DATE(fecha_emision) AS dia, COALESCE(SUM(total),0) AS ingresos FROM facturas WHERE empresa_id = '{self.tenant_id}' GROUP BY DATE(fecha_emision) ORDER BY dia DESC LIMIT 30"
        # AVANCE VEHICULO (20+)
        if ("avance del vehiculo" in q) or ("avances del vehiculo" in q):
            return ("SELECT c.id AS cita_id, v.placa, av.tipo, av.estado_nuevo, av.mensaje, av.porcentaje_avance, av.created_at "
                    "FROM avances_vehiculo av JOIN citas c ON c.id = av.cita_id JOIN vehiculos v ON v.id = c.vehiculo_id "
                    f"WHERE av.empresa_id = '{self.tenant_id}' ORDER BY av.created_at DESC LIMIT 200")
        if ("ultimo avance por vehiculo" in q):
            return ("SELECT v.placa, MAX(av.created_at) AS ultimo_avance "
                    "FROM avances_vehiculo av JOIN citas c ON c.id=av.cita_id JOIN vehiculos v ON v.id=c.vehiculo_id "
                    f"WHERE av.empresa_id = '{self.tenant_id}' GROUP BY v.placa ORDER BY ultimo_avance DESC")
        if ("avances visibles al cliente" in q):
            return f"SELECT cita_id, tipo, estado_nuevo, mensaje, created_at FROM avances_vehiculo WHERE empresa_id = '{self.tenant_id}' AND visible_cliente = true ORDER BY created_at DESC LIMIT 200"
        if ("avances no visibles" in q):
            return f"SELECT cita_id, tipo, estado_nuevo, mensaje, created_at FROM avances_vehiculo WHERE empresa_id = '{self.tenant_id}' AND visible_cliente = false ORDER BY created_at DESC LIMIT 200"
        if ("porcentaje de avance" in q):
            return ("SELECT v.placa, MAX(av.porcentaje_avance) AS ultimo_porcentaje "
                    "FROM avances_vehiculo av JOIN citas c ON c.id=av.cita_id JOIN vehiculos v ON v.id=c.vehiculo_id "
                    f"WHERE av.empresa_id = '{self.tenant_id}' GROUP BY v.placa ORDER BY ultimo_porcentaje DESC NULLS LAST")
        if ("vehiculos sin avances" in q):
            return ("SELECT v.placa, v.marca, v.modelo FROM vehiculos v "
                    "LEFT JOIN citas c ON c.vehiculo_id = v.id LEFT JOIN avances_vehiculo av ON av.cita_id = c.id "
                    f"WHERE v.empresa_id = '{self.tenant_id}' GROUP BY v.id,v.placa,v.marca,v.modelo HAVING COUNT(av.id)=0 ORDER BY v.placa")
        if ("avances por tipo" in q):
            return f"SELECT tipo, COUNT(*) AS total FROM avances_vehiculo WHERE empresa_id = '{self.tenant_id}' GROUP BY tipo ORDER BY total DESC"
        if ("avances de hoy" in q):
            return f"SELECT cita_id, tipo, estado_nuevo, mensaje, created_at FROM avances_vehiculo WHERE empresa_id = '{self.tenant_id}' AND DATE(created_at)=CURRENT_DATE ORDER BY created_at DESC"
        if ("avances de esta semana" in q):
            return f"SELECT cita_id, tipo, estado_nuevo, mensaje, created_at FROM avances_vehiculo WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('week', now()) ORDER BY created_at DESC"
        if ("avances de este mes" in q):
            return f"SELECT cita_id, tipo, estado_nuevo, mensaje, created_at FROM avances_vehiculo WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('month', now()) ORDER BY created_at DESC"
        if ("cantidad de avances por cita" in q):
            return f"SELECT cita_id, COUNT(*) AS total_avances FROM avances_vehiculo WHERE empresa_id = '{self.tenant_id}' GROUP BY cita_id ORDER BY total_avances DESC LIMIT 50"
        if ("avances por mecanico" in q) or ("avances por usuario" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS usuario, COUNT(av.id) AS avances "
                    "FROM avances_vehiculo av LEFT JOIN usuarios u ON u.id = av.registrado_por_id "
                    f"WHERE av.empresa_id = '{self.tenant_id}' GROUP BY u.nombres,u.apellidos ORDER BY avances DESC")
        if ("tiempo desde ultimo avance" in q):
            return ("SELECT v.placa, NOW() - MAX(av.created_at) AS tiempo_desde_ultimo_avance "
                    "FROM avances_vehiculo av JOIN citas c ON c.id=av.cita_id JOIN vehiculos v ON v.id=c.vehiculo_id "
                    f"WHERE av.empresa_id = '{self.tenant_id}' GROUP BY v.placa ORDER BY tiempo_desde_ultimo_avance DESC")
        if ("estado actual por vehiculo" in q):
            return ("SELECT v.placa, MAX(av.created_at) AS fecha, "
                    "MAX(av.estado_nuevo) AS estado_reportado "
                    "FROM avances_vehiculo av JOIN citas c ON c.id=av.cita_id JOIN vehiculos v ON v.id=c.vehiculo_id "
                    f"WHERE av.empresa_id = '{self.tenant_id}' GROUP BY v.placa ORDER BY fecha DESC")
        # SOLICITUDES DE REPUESTO (20+)
        if ("solicitudes de repuesto" in q):
            return f"SELECT id, estado, created_at FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' ORDER BY created_at DESC LIMIT 200"
        if ("solicitudes pendientes" in q and "repuesto" in q):
            return f"SELECT id, estado, created_at FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' AND estado IN ('CREADA','APROBADA_POR_ASESOR','EN_REVISION_ALMACEN','PARCIALMENTE_DISPONIBLE') ORDER BY created_at DESC"
        if ("solicitudes entregadas" in q):
            return f"SELECT id, estado, updated_at FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' AND estado='ENTREGADA' ORDER BY updated_at DESC"
        if ("solicitudes cerradas" in q):
            return f"SELECT id, estado, updated_at FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' AND estado='CERRADA' ORDER BY updated_at DESC"
        if ("detalle de solicitudes" in q):
            return ("SELECT sr.id AS solicitud_id, i.nombre AS item, srd.cantidad_solicitada, srd.cantidad_aprobada, srd.cantidad_entregada, srd.estado "
                    "FROM solicitudes_repuesto_detalle srd JOIN solicitudes_repuesto sr ON sr.id=srd.solicitud_id "
                    "LEFT JOIN items_inventario i ON i.id=srd.item_inventario_id "
                    f"WHERE srd.empresa_id = '{self.tenant_id}' ORDER BY sr.id DESC LIMIT 300")
        if ("items mas solicitados" in q):
            return ("SELECT i.nombre, COALESCE(SUM(srd.cantidad_solicitada),0) AS cantidad "
                    "FROM solicitudes_repuesto_detalle srd LEFT JOIN items_inventario i ON i.id=srd.item_inventario_id "
                    f"WHERE srd.empresa_id = '{self.tenant_id}' GROUP BY i.nombre ORDER BY cantidad DESC LIMIT 30")
        if ("solicitudes sin stock" in q):
            return f"SELECT solicitud_id, item_inventario_id, cantidad_solicitada, estado FROM solicitudes_repuesto_detalle WHERE empresa_id = '{self.tenant_id}' AND estado='SIN_STOCK' ORDER BY created_at DESC"
        if ("solicitudes parciales" in q):
            return f"SELECT solicitud_id, item_inventario_id, cantidad_solicitada, cantidad_entregada, estado FROM solicitudes_repuesto_detalle WHERE empresa_id = '{self.tenant_id}' AND estado IN ('PARCIAL','PARCIALMENTE_DISPONIBLE') ORDER BY created_at DESC"
        if ("solicitudes por estado" in q):
            return f"SELECT estado, COUNT(*) AS total FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' GROUP BY estado ORDER BY total DESC"
        if ("solicitudes de hoy" in q):
            return f"SELECT id, estado, created_at FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' AND DATE(created_at)=CURRENT_DATE ORDER BY created_at DESC"
        if ("solicitudes de esta semana" in q):
            return f"SELECT id, estado, created_at FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('week', now()) ORDER BY created_at DESC"
        if ("solicitudes de este mes" in q):
            return f"SELECT id, estado, created_at FROM solicitudes_repuesto WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('month', now()) ORDER BY created_at DESC"
        if ("solicitudes por mecanico" in q) or ("solicitudes por asesor" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS usuario, COUNT(sr.id) AS total "
                    "FROM solicitudes_repuesto sr LEFT JOIN usuarios u ON u.id=sr.solicitado_por_id "
                    f"WHERE sr.empresa_id = '{self.tenant_id}' GROUP BY u.nombres,u.apellidos ORDER BY total DESC")
        # VENTAS PRESENCIALES (15+)
        if ("ventas presenciales" in q) or ("ventas mostrador" in q):
            return f"SELECT id, estado, subtotal, total, created_at FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' ORDER BY created_at DESC LIMIT 200"
        if ("ventas presenciales de hoy" in q):
            return f"SELECT id, estado, total, created_at FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' AND DATE(created_at)=CURRENT_DATE ORDER BY created_at DESC"
        if ("ventas presenciales de esta semana" in q):
            return f"SELECT id, estado, total, created_at FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('week', now()) ORDER BY created_at DESC"
        if ("ventas presenciales de este mes" in q):
            return f"SELECT id, estado, total, created_at FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('month', now()) ORDER BY created_at DESC"
        if ("ventas presenciales por estado" in q):
            return f"SELECT estado, COUNT(*) AS total, COALESCE(SUM(total),0) AS monto FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' GROUP BY estado ORDER BY monto DESC"
        if ("detalle ventas presenciales" in q):
            return ("SELECT v.id AS venta_id, i.nombre AS item, vd.cantidad, vd.precio_unitario, vd.subtotal "
                    "FROM ventas_mostrador_detalle vd JOIN ventas_mostrador v ON v.id=vd.venta_id "
                    "LEFT JOIN items_inventario i ON i.id=vd.item_inventario_id "
                    f"WHERE vd.empresa_id = '{self.tenant_id}' ORDER BY v.created_at DESC LIMIT 300")
        if ("top clientes ventas presenciales" in q):
            return ("SELECT COALESCE(u.nombres || ' ' || u.apellidos, v.cliente_nombre_libre, 'SIN_CLIENTE') AS cliente, COUNT(v.id) AS ventas, COALESCE(SUM(v.total),0) AS total "
                    "FROM ventas_mostrador v LEFT JOIN usuarios u ON u.id = v.cliente_usuario_id "
                    f"WHERE v.empresa_id = '{self.tenant_id}' AND v.estado='CONFIRMADA' GROUP BY COALESCE(u.nombres || ' ' || u.apellidos, v.cliente_nombre_libre, 'SIN_CLIENTE') ORDER BY total DESC LIMIT 20")
        if ("top vendedores" in q):
            return ("SELECT u.nombres || ' ' || COALESCE(u.apellidos,'') AS vendedor, COUNT(v.id) AS ventas, COALESCE(SUM(v.total),0) AS total "
                    "FROM ventas_mostrador v LEFT JOIN usuarios u ON u.id=v.vendido_por_id "
                    f"WHERE v.empresa_id = '{self.tenant_id}' AND v.estado='CONFIRMADA' GROUP BY u.nombres,u.apellidos ORDER BY total DESC")
        if ("ventas anuladas" in q):
            return f"SELECT id, estado, total, created_at FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' AND estado='ANULADA' ORDER BY created_at DESC"
        if ("ventas confirmadas" in q):
            return f"SELECT id, estado, total, created_at FROM ventas_mostrador WHERE empresa_id = '{self.tenant_id}' AND estado='CONFIRMADA' ORDER BY created_at DESC"
        # CAJA Y MOVIMIENTOS (10+)
        if ("movimientos de caja" in q) or ("caja y movimientos" in q):
            return f"SELECT id, tipo_movimiento, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' ORDER BY created_at DESC LIMIT 200"
        if ("ingresos de caja" in q):
            return f"SELECT id, tipo_movimiento, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND tipo_movimiento='INGRESO' ORDER BY created_at DESC"
        if ("egresos de caja" in q):
            return f"SELECT id, tipo_movimiento, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND tipo_movimiento='EGRESO' ORDER BY created_at DESC"
        if ("resumen de caja hoy" in q):
            return f"SELECT tipo_movimiento, COALESCE(SUM(monto),0) AS total FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND DATE(created_at)=CURRENT_DATE GROUP BY tipo_movimiento"
        if ("saldo de caja" in q):
            return ("SELECT "
                    "COALESCE(SUM(CASE WHEN tipo_movimiento='INGRESO' THEN monto ELSE 0 END),0) - "
                    "COALESCE(SUM(CASE WHEN tipo_movimiento='EGRESO' THEN monto ELSE 0 END),0) AS saldo "
                    f"FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}'")
        if ("movimientos de caja de hoy" in q):
            return f"SELECT id, tipo_movimiento, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND DATE(created_at)=CURRENT_DATE ORDER BY created_at DESC"
        if ("movimientos de caja de esta semana" in q):
            return f"SELECT id, tipo_movimiento, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('week', now()) ORDER BY created_at DESC"
        if ("movimientos de caja de este mes" in q):
            return f"SELECT id, tipo_movimiento, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND created_at >= date_trunc('month', now()) ORDER BY created_at DESC"
        if ("ajustes de caja" in q):
            return f"SELECT id, tipo_movimiento, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND tipo_movimiento='AJUSTE' ORDER BY created_at DESC"
        if ("top egresos de caja" in q):
            return f"SELECT id, monto, concepto, created_at FROM movimientos_caja WHERE empresa_id = '{self.tenant_id}' AND tipo_movimiento='EGRESO' ORDER BY monto DESC LIMIT 20"
        return ""
    def _sanitize_sql(self, sql: str) -> str:
        """
        Aplica correcciones defensivas para errores frecuentes de columnas
        alucinadas por el LLM.
        """
        if not sql:
            return sql
        fixed_sql = sql
        # En el esquema real `roles` usa columna `nombre`, no `rol`.
        fixed_sql = re.sub(r"\br\.rol\b", "r.nombre", fixed_sql, flags=re.IGNORECASE)
        # Correcciones de columnas comunes por tabla.
        # `citas_detalles` usa `precio_referencial`, no `precio_unitario`.
        fixed_sql = re.sub(r"\bcd\.precio_unitario\b", "cd.precio_referencial", fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r"\bcitas_detalles\.precio_unitario\b", "citas_detalles.precio_referencial", fixed_sql, flags=re.IGNORECASE)
        # `presupuestos_detalle` usa `precio_unitario`, no `precio_referencial`.
        fixed_sql = re.sub(r"\bpd\.precio_referencial\b", "pd.precio_unitario", fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r"\bpresupuestos_detalle\.precio_referencial\b", "presupuestos_detalle.precio_unitario", fixed_sql, flags=re.IGNORECASE)
        # Corrección frecuente de alias: `c` suele ser citas, no usuarios.
        fixed_sql = re.sub(r"\bc\.nombres\b", "u.nombres", fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r"\bc\.apellidos\b", "u.apellidos", fixed_sql, flags=re.IGNORECASE)
        # `ordenes_trabajo_detalle` referencias reales.
        fixed_sql = re.sub(r"\bod\.servicio_id\b", "od.servicio_catalogo_id", fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r"\bordenes_trabajo_detalle\.servicio_id\b", "ordenes_trabajo_detalle.servicio_catalogo_id", fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r"\bod\.descripcion\b", "COALESCE(od.observaciones_mecanico, od.observaciones_asesor)", fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r"\bod\.fecha_realizacion\b", "od.fin_real", fixed_sql, flags=re.IGNORECASE)
        # `planes_servicio_vehiculo` no tiene `nombre`.
        fixed_sql = re.sub(r"\bp\.nombre\b", "p.descripcion_general", fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r"\bplanes_servicio_vehiculo\.nombre\b", "planes_servicio_vehiculo.descripcion_general", fixed_sql, flags=re.IGNORECASE)
        # Si intenta unir vehiculo directo desde ordenes_trabajo_detalle (no existe vehiculo_id),
        # rehacer JOIN por orden_global -> cita -> vehiculo.
        fixed_sql = re.sub(
            r"JOIN\s+vehiculos\s+v\s+ON\s+od\.vehiculo_id\s*=\s*v\.id",
            "JOIN ordenes_trabajo_global og ON od.orden_global_id = og.id JOIN citas c ON og.cita_id = c.id JOIN vehiculos v ON c.vehiculo_id = v.id",
            fixed_sql,
            flags=re.IGNORECASE,
        )
        # Evitar join inválido de espacios directo con citas.
        fixed_sql = re.sub(
            r"JOIN\s+citas\s+c\s+ON\s+e\.id\s*=\s*c\.espacio_trabajo_id",
            "JOIN citas_espacios_segmentos ces ON ces.espacio_trabajo_id = e.id JOIN citas c ON c.id = ces.cita_id",
            fixed_sql,
            flags=re.IGNORECASE,
        )
        return fixed_sql
    def run_sql(self, sql: str) -> Any:
        """
        Sobrescribe el método de ejecución de SQL para usar la conexión de Django.
        Aplica validación de seguridad antes de ejecutar.
        """
        import pandas as pd
        
        # Validación de seguridad rudimentaria: 
        # Asegurarse de que el SQL contiene el filtro de empresa_id o al menos un JOIN que lo haga
        if f"'{self.tenant_id}'" not in sql:
            # Fallback agresivo
            raise PermissionError("Bloqueo de Seguridad: La consulta generada no filtra por tu empresa_id.")
            
        # Ejecutar la consulta a través de Django ORM (connection.cursor)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                # Obtener nombres de columnas
                columns = [col[0] for col in cursor.description]
                # Obtener datos
                data = cursor.fetchall()
                
            # Retornar como DataFrame de Pandas (Vanna espera un DataFrame)
            return pd.DataFrame(data, columns=columns)
        except Exception as e:
            print(f"Error ejecutando SQL dinámico: {e}\\nSQL: {sql}")
            raise e

    # --- Implementación manual básica de RAG para evitar dependencias externas como Chroma/PgVector en esta fase ---
    def add_ddl(self, ddl: str, **kwargs):
        self._ddl_cache.append(ddl)
        
    def _extract_table_name(self, ddl: str) -> str:
        match = re.search(r"CREATE TABLE\s+([a-zA-Z0-9_]+)\s*\(", ddl, flags=re.IGNORECASE)
        return match.group(1).lower() if match else ""

    def _select_tables_for_question(self, question: str) -> set:
        q = (question or "").lower()
        base_tables = {"usuarios", "roles"}

        mapping = {
            "vehicul": {"vehiculos"},
            "plan": {"planes_servicio_vehiculo", "planes_servicio_detalle", "servicios_catalogo", "vehiculos"},
            "cita": {"citas", "citas_detalles", "usuarios", "vehiculos"},
            "servicio": {"servicios_catalogo", "citas_detalles"},
            "presupuesto": {"presupuestos_cita", "presupuestos_detalle", "servicios_catalogo"},
            "orden": {"ordenes_trabajo_global", "ordenes_trabajo_detalle", "usuarios"},
            "mecanic": {"ordenes_trabajo_detalle", "usuarios"},
            "inventario": {"items_inventario", "categorias_inventario"},
            "repuesto": {"items_inventario", "categorias_inventario"},
            "compra": {"compras", "compras_detalle"},
            "pago": {"pagos_taller", "facturas"},
            "factura": {"facturas", "pagos_taller"},
            "venta": {"ventas_mostrador", "ventas_mostrador_detalle"},
            "ingreso": {"facturas", "pagos_taller"},
        }
        for key, tables in mapping.items():
            if key in q:
                base_tables.update(tables)
        return base_tables

    def get_related_ddl(self, question: str, **kwargs) -> list:
        selected_tables = self._select_tables_for_question(question)
        prioritized = []
        remaining = []
        for ddl in self._ddl_cache:
            table = self._extract_table_name(ddl)
            if table in selected_tables:
                prioritized.append(ddl)
            else:
                remaining.append(ddl)
        max_tables = 8
        return (prioritized + remaining)[:max_tables]
        
    def add_sql(self, question: str, sql: str, **kwargs):
        self._sql_cache.append({"question": question, "sql": sql})
        
    def get_similar_question_sql(self, question: str, **kwargs) -> list:
        return self._sql_cache[-4:]

    def add_documentation(self, documentation: str, **kwargs):
        pass

    def get_related_documentation(self, question: str, **kwargs) -> list:
        return []

    # Compatibilidad con versiones nuevas de VannaBase
    def add_question_sql(self, question: str, sql: str, **kwargs) -> str:
        self.add_sql(question=question, sql=sql, **kwargs)
        return "dummy-id"

    def generate_embedding(self, data: str, **kwargs) -> List[float]:
        return [0.0]

    def get_training_data(self, **kwargs) -> Any:
        import pandas as pd
        return pd.DataFrame()

    def remove_training_data(self, id: str, **kwargs) -> bool:
        return True

    def generate_plotly(self, df, **kwargs):
        """
        Genera un gráfico Plotly básico a partir del DataFrame devuelto.
        """
        import plotly.express as px
        
        if df is None or df.empty or len(df.columns) == 0:
            return None
            
        columns = df.columns.tolist()
        
        try:
            if len(columns) == 1:
                return px.bar(df, y=columns[0], title="Resultado")
            else:
                x_col = columns[0]
                y_col = columns[1]
                
                # Si hay más de dos columnas y la segunda no es numérica pero la tercera sí,
                # o si la primera columna parece una categoría (string o fecha).
                # Plotly Express generalmente es inteligente con x e y.
                return px.bar(df, x=x_col, y=y_col, title="Visualización de Datos")
        except Exception as e:
            print(f"Error generando gráfico: {e}")
            return None