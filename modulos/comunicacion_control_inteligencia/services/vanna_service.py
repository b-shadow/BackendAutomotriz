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
            'administracion_acceso_configuracion.Usuario'
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
            res = self.groq_client.chat.completions.create(
                model=self.model,
                messages=prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}],
                temperature=0.1, # Temperatura baja para código SQL más determinista
                max_tokens=1024,
            )
            return res.choices[0].message.content
        except Exception as e:
            print(f"Error en VannaAutomotrizService.submit_prompt: {str(e)}")
            raise e

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
        
    def get_related_ddl(self, question: str, **kwargs) -> list:
        return self._ddl_cache
        
    def add_sql(self, question: str, sql: str, **kwargs):
        self._sql_cache.append({"question": question, "sql": sql})
        
    def get_similar_question_sql(self, question: str, **kwargs) -> list:
        return self._sql_cache

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
