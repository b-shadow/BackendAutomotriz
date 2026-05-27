from rest_framework import viewsets, status, response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
import json

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
            
            # Ejecutar SQL y obtener DataFrame
            df = vanna_service.run_sql(sql)
            
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
            return response.Response(
                {"error": f"Error al generar el reporte: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def transcribe_audio(self, request, *args, **kwargs):
        """
        Endpoint que recibe un archivo de audio y utiliza Groq Whisper
        para transcribirlo a texto.
        """
        audio_file = request.FILES.get('audio')
        if not audio_file:
            return response.Response(
                {"error": "No se proporcionó ningún archivo de audio."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        import os
        from groq import Groq
        
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return response.Response(
                {"error": "GROQ_API_KEY no está configurada."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
        try:
            client = Groq(api_key=api_key)
            transcription = client.audio.transcriptions.create(
              file=("audio.webm", audio_file.read()),
              model="whisper-large-v3-turbo",
              language="es",
              response_format="json"
            )
            
            return response.Response({
                "text": transcription.text
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return response.Response(
                {"error": f"Error en la transcripción: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            import traceback
            traceback.print_exc()
            return response.Response(
                {"error": f"Error al generar el reporte: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
