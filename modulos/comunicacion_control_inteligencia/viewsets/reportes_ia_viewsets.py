from rest_framework import viewsets, status, response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
import json
import traceback

from modulos.comunicacion_control_inteligencia.services.vanna_service import VannaAutomotrizService

class ReportesIAViewSet(viewsets.ViewSet):
    """
    ViewSet para manejar la generación de reportes dinámicos vía Vanna AI.
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def ask(self, request, *args, **kwargs):
        """
        Endpoint que recibe una pregunta en lenguaje natural y devuelve
        los datos estructurados y el gráfico generados por Vanna AI.
        """
        prompt = request.data.get('prompt')
        if not prompt:
            return response.Response(
                {"error": "El campo 'prompt' es requerido."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            # Inicializamos el servicio de Vanna con el tenant actual
            vanna_service = VannaAutomotrizService(tenant_id=request.user.empresa_id)
            
            # Generar SQL (Vanna se encarga del RAG interno)
            sql = vanna_service.generate_sql(question=prompt)
            df = None
            last_error = None

            # Ejecutar SQL con autocorrección progresiva.
            # Intento 1: SQL original
            # Intento 2: SQL reparado con mensaje de error
            # Intento 3: SQL forzado por intención del prompt
            for attempt in range(3):
                try:
                    df = vanna_service.run_sql(sql)
                    last_error = None
                    break
                except Exception as exec_error:
                    last_error = exec_error
                    if attempt == 0:
                        sql = vanna_service.repair_sql_with_error(sql, str(exec_error))
                    elif attempt == 1:
                        forced_sql = vanna_service._build_forced_sql_from_prompt(prompt)
                        if forced_sql:
                            sql = vanna_service._sanitize_sql(forced_sql)
                    else:
                        break

            if last_error is not None:
                raise last_error
            
            # Generar gráfico Plotly (Devuelve objeto Figure)
            fig = vanna_service.generate_plotly(df)
            
            # Extraer JSON del gráfico si es posible
            plotly_json = None
            if fig:
                import plotly.io as pio
                plotly_json = json.loads(pio.to_json(fig))
                
            # Extraer datos crudos como lista de diccionarios para la tabla
            data_records = df.to_dict(orient="records")
            
            return response.Response({
                "sql": sql,
                "data": data_records,
                "plotly_fig": plotly_json
            }, status=status.HTTP_200_OK)
            
        except PermissionError as pe:
            return response.Response(
                {"error": str(pe)},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            traceback.print_exc()
            return response.Response(
                {"error": f"Error al generar el reporte: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
