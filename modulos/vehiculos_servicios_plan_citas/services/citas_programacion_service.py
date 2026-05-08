"""
Servicio de ProgramaciÃ³n de Citas - CU18

Centraliza toda la lÃ³gica de:
  - ValidaciÃ³n temporal (fecha/hora no en el pasado)
  - CÃ¡lculo de disponibilidad de espacios
  - FragmentaciÃ³n de reservas (intra-dÃ­a y multi-dÃ­a)
  - ConstrucciÃ³n de segmentos canÃ³nicos
  
PropÃ³sito: Ser la fuente de verdad del backend para programaciÃ³n de citas.
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Optional
from django.utils import timezone
from django.db.models import Q

from modulos.vehiculos_servicios_plan_citas.models import (
    Cita,
    CitaEspacioSegmento,
    EspacioTrabajo,
    HorarioEspacioTrabajo,
    EstadoCita,
)
from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.vehiculos_servicios_plan_citas.services.bloques_tiempo import BLOQUE_MINUTOS


class ResultadoProgramacion:
    """Resultado de un intento de programaciÃ³n."""

    def __init__(
        self,
        valido: bool,
        fragmentado: bool = False,
        segmentos: Optional[List[Dict]] = None,
        duracion_total_min: int = 0,
        error: Optional[str] = None,
    ):
        self.valido = valido
        self.fragmentado = fragmentado
        self.segmentos = segmentos or []
        self.duracion_total_min = duracion_total_min
        self.error = error

    def to_dict(self):
        """Convierte a diccionario para serializaciÃ³n."""
        return {
            "valido": self.valido,
            "fragmentado": self.fragmentado,
            "segmentos": self.segmentos,
            "duracion_total_min": self.duracion_total_min,
            "error": self.error,
        }


class CitasProgramacionService:
    """Servicio de lÃ³gica de programaciÃ³n de citas."""

    HORIZONTE_BUSQUEDA_DIAS = 30
    BUFFER_MINUTO_HOY = 5

    @staticmethod
    def _redondear_hacia_arriba_bloque(minuto: int) -> int:
        """Redondea un minuto al siguiente inicio de bloque de 30 min."""
        if minuto % BLOQUE_MINUTOS == 0:
            return minuto
        return minuto + (BLOQUE_MINUTOS - (minuto % BLOQUE_MINUTOS))

    @staticmethod
    def _bloques_inicio_desde_ventanas(
        ventanas_libres: List[Tuple[int, int]],
        inicio_minimo: Optional[int] = None,
    ) -> List[int]:
        """
        Genera inicios de bloques válidos (30 min) contenidos en ventanas libres.
        """
        bloques = []
        for ventana_inicio, ventana_fin in ventanas_libres:
            inicio = CitasProgramacionService._redondear_hacia_arriba_bloque(ventana_inicio)
            if inicio_minimo is not None:
                inicio = max(inicio, CitasProgramacionService._redondear_hacia_arriba_bloque(inicio_minimo))

            while inicio + BLOQUE_MINUTOS <= ventana_fin:
                bloques.append(inicio)
                inicio += BLOQUE_MINUTOS
        return sorted(set(bloques))

    @staticmethod
    def _minuto_operativo_a_dt_utc(
        fecha_operativa: datetime,
        minuto_inicio: int,
        minuto_fin: int,
        tz_operativa,
    ) -> Tuple[datetime, datetime]:
        """Convierte minutos del día operativo a datetimes UTC."""
        inicio_dt_operativo = tz_operativa.localize(
            datetime.combine(
                fecha_operativa.date(),
                datetime.min.time().replace(
                    hour=minuto_inicio // 60,
                    minute=minuto_inicio % 60,
                ),
            )
        )
        fin_dt_operativo = tz_operativa.localize(
            datetime.combine(
                fecha_operativa.date(),
                datetime.min.time().replace(
                    hour=minuto_fin // 60,
                    minute=minuto_fin % 60,
                ),
            )
        )
        return inicio_dt_operativo.astimezone(timezone.utc), fin_dt_operativo.astimezone(timezone.utc)

    @staticmethod
    def obtener_timezone_operativa(empresa: Empresa):
        """
        Obtiene la timezone operativa del negocio asociado a la empresa.
        
        Fallback: America/La_Paz si no estÃ¡ configurada.
        """
        from pytz import timezone as pytz_timezone
        
        timezone_str = getattr(empresa, 'timezone_operativa', None) or 'America/La_Paz'
        try:
            return pytz_timezone(timezone_str)
        except Exception:
            return pytz_timezone('America/La_Paz')

    @staticmethod
    def normalizar_datetime_operativo(dt: datetime, empresa: Empresa) -> datetime:
        """
        Convierte un datetime a la timezone operativa del negocio.
        
        - Si dt es naive, lo interpreta como UTC y lo convierte a operativo
        - Si dt es aware UTC, lo convierte a operativo
        - Retorna siempre datetime aware en timezone operativa
        """
        if dt is None:
            return None
        
        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        
        # Si es naive, interpretar como UTC
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        
        # Convertir a timezone operativa
        return dt.astimezone(tz_operativa)

    @staticmethod
    def validar_inicio_no_pasado(
        fecha_hora_inicio: datetime, empresa: Empresa
    ) -> Tuple[bool, Optional[str]]:
        """
        Valida que fecha_hora_inicio no estÃ© en el pasado.

        Reglas:
        - No puede ser antes de "ahora"
        - Si es hoy, al menos BUFFER_MINUTO_HOY minutos en el futuro
        - Timezone-aware

        Returns:
            Tupla (valido, error_message)
        """
        ahora = timezone.now()

        # Asegurar que ambas son timezone-aware
        if fecha_hora_inicio.tzinfo is None:
            fecha_hora_inicio = timezone.make_aware(fecha_hora_inicio)

        # Si es hoy
        if fecha_hora_inicio.date() == ahora.date():
            minimo_requerido = ahora + timedelta(minutes=CitasProgramacionService.BUFFER_MINUTO_HOY)
            if fecha_hora_inicio < minimo_requerido:
                hora_ahora = ahora.strftime("%H:%M")
                return (
                    False,
                    f"Debes solicitar al menos {CitasProgramacionService.BUFFER_MINUTO_HOY} minutos en el futuro. "
                    f"Ahora son las {hora_ahora}.",
                )
        else:
            # Si es fecha futura pero hora estÃ¡ en el pasado
            if fecha_hora_inicio < ahora:
                return False, "No puedes solicitar una cita en el pasado."

        return True, None

    @staticmethod
    def obtener_ventanas_operativas_dia(
        espacio_id: str, fecha: datetime, empresa: Empresa
    ) -> List[Tuple[int, int]]:
        """
        Obtiene ventanas operativas de un espacio para un dÃ­a especÃ­fico.

        Devuelve lista de tuplas (hora_inicio_min, hora_fin_min) en minutos desde medianoche.
        Usa HorarioEspacioTrabajo.
        
        CORRECCIÃ“N: Normaliza fecha a timezone operativa antes de calcular dÃ­a de semana.

        Args:
            espacio_id: UUID del espacio
            fecha: Fecha (solo se usa el dÃ­a de la semana, serÃ¡ normalizada a tz operativa)
            empresa: Empresa (para validar pertenencia)

        Returns:
            [(hora_inicio_minutos, hora_fin_minutos), ...] en minutos de tz operativa
            Ordenado por hora inicio.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # CORRECCIÃ“N: Normalizar fecha a timezone operativa
        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        fecha_operativa = CitasProgramacionService.normalizar_datetime_operativo(fecha, empresa)
        
        # Calcular dÃ­a de la semana EN TIMEZONE OPERATIVA (0 = Lunes, 6 = Domingo)
        dia_semana = fecha_operativa.weekday()
        
        logger.debug(
            f"[obtener_ventanas_operativas_dia] espacio_id={espacio_id}, "
            f"fecha_input={fecha}, fecha_operativa={fecha_operativa}, "
            f"dia_semana={dia_semana}"
        )

        horarios = HorarioEspacioTrabajo.objects.filter(
            espacio_trabajo_id=espacio_id,
            dia_semana=dia_semana,
            activo=True,
            empresa=empresa,
        ).order_by("hora_inicio")

        ventanas = []
        for h in horarios:
            inicio_min = h.hora_inicio.hour * 60 + h.hora_inicio.minute
            fin_min = h.hora_fin.hour * 60 + h.hora_fin.minute
            ventanas.append((inicio_min, fin_min))
            logger.debug(
                f"[obtener_ventanas_operativas_dia] Horario: {h.hora_inicio} â†’ {h.hora_fin} "
                f"({inicio_min}min â†’ {fin_min}min)"
            )

        return ventanas


    @staticmethod
    def obtener_ocupacion_espacio_dia(
        espacio_id: str, fecha: datetime, empresa: Empresa
    ) -> List[Tuple[int, int]]:
        """
        Obtiene intervalos ocupados de un espacio para un dÃ­a especÃ­fico.

        Extrae de CitaEspacioSegmento con citas activas.
        CORRECCIÃ“N: Normaliza datetimes a timezone operativa antes de calcular minutos.

        Args:
            espacio_id: UUID del espacio (string)
            fecha: Fecha especifica
            empresa: Empresa

        Returns:
            [(inicio_minutos, fin_minutos), ...] en minutaje de la timezone operativa
            Ordenado por inicio.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        
        # Citas que ocupan agenda
        estados_ocupados = [
            EstadoCita.PROGRAMADA,
            EstadoCita.EN_ESPERA_INGRESO,
            EstadoCita.EN_PROCESO,
        ]

        # Convertir fecha a timezone operativa para determinar lÃ­mites del dÃ­a
        fecha_operativa = fecha.astimezone(tz_operativa) if fecha.tzinfo else fecha

        # Inicio y fin del dÃ­a en timezone operativa
        inicio_dia_operativo = tz_operativa.localize(
            datetime.combine(fecha_operativa.date(), datetime.min.time())
        )
        fin_dia_operativo = tz_operativa.localize(
            datetime.combine(fecha_operativa.date() + timedelta(days=1), datetime.min.time())
        )

        # Convertir a UTC para query en BD
        inicio_dia_utc = inicio_dia_operativo.astimezone(timezone.utc)
        fin_dia_utc = fin_dia_operativo.astimezone(timezone.utc)

        logger.debug(
            f"[obtener_ocupacion_espacio_dia] espacio_id={espacio_id}, "
            f"fecha={fecha_operativa.date()}, "
            f"rango_operativo={inicio_dia_operativo} â†’ {fin_dia_operativo}, "
            f"rango_utc={inicio_dia_utc} â†’ {fin_dia_utc}"
        )

        # Query en UTC (como estÃ¡ almacenado en BD)
        segmentos = CitaEspacioSegmento.objects.filter(
            espacio_trabajo_id=espacio_id,
            cita__empresa=empresa,
            cita__estado__in=estados_ocupados,
            inicio_programado__lt=fin_dia_utc,
            fin_programado__gt=inicio_dia_utc,
        ).order_by("inicio_programado")

        logger.debug(f"[obtener_ocupacion_espacio_dia] Encontrados {segmentos.count()} segmentos ocupados")

        ocupacion = []
        for seg in segmentos:
            # CORRECCIÃ“N CRÃTICA: Normalizar a timezone operativa antes de extraer hora/minuto
            inicio_operativo = seg.inicio_programado.astimezone(tz_operativa)
            fin_operativo = seg.fin_programado.astimezone(tz_operativa)

            # Solo incluir si la porciÃ³n en timezone operativa estÃ¡ dentro del dÃ­a
            # (maneja segmentos que cruzan medianoche)
            if inicio_operativo.date() <= fecha_operativa.date():
                if fin_operativo.date() >= fecha_operativa.date():
                    # Truncar al rango del dÃ­a si es necesario
                    inicio_min = max(inicio_operativo.hour * 60 + inicio_operativo.minute, 0)
                    fin_min = min(fin_operativo.hour * 60 + fin_operativo.minute, 24 * 60)
                    
                    ocupacion.append((inicio_min, fin_min))
                    logger.debug(
                        f"[obtener_ocupacion_espacio_dia] Segmento (UTC: {seg.inicio_programado} â†’ {seg.fin_programado}) "
                        f"â†’ Operativo: {inicio_operativo} â†’ {fin_operativo} "
                        f"â†’ Minutaje: {inicio_min}min â†’ {fin_min}min"
                    )

        return ocupacion


    @staticmethod
    def restar_ocupacion_ventanas(
        ventanas: List[Tuple[int, int]],
        ocupacion: List[Tuple[int, int]],
    ) -> List[Tuple[int, int]]:
        """
        Resta intervalos ocupados de ventanas operativas.

        Algoritmo: Para cada ventana, resta todos los intervalos ocupados que se solapan.

        Args:
            ventanas: [(inicio_min, fin_min), ...]
            ocupacion: [(inicio_min, fin_min), ...]

        Returns:
            [(inicio_min, fin_min), ...] ventanas resultantes libres
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.debug(f"[restar_ocupacion_ventanas] Ventanas: {ventanas}, Ocupacion: {ocupacion}")
        
        if not ventanas:
            logger.debug("[restar_ocupacion_ventanas] Sin ventanas, retornando []")
            return []

        if not ocupacion:
            logger.debug("[restar_ocupacion_ventanas] Sin ocupacion, retornando ventanas originales")
            return ventanas

        resultado = []

        for vent_inicio, vent_fin in ventanas:
            # Empezar con la ventana completa
            segmentos_libres = [(vent_inicio, vent_fin)]

            # Restar cada intervalo ocupado
            for ocup_inicio, ocup_fin in ocupacion:
                nuevos_segmentos = []

                for seg_inicio, seg_fin in segmentos_libres:
                    # Sin solapamiento
                    if ocup_fin <= seg_inicio or ocup_inicio >= seg_fin:
                        nuevos_segmentos.append((seg_inicio, seg_fin))
                    else:
                        # Hay solapamiento, partir el segmento
                        if seg_inicio < ocup_inicio:
                            nuevos_segmentos.append((seg_inicio, ocup_inicio))
                        if seg_fin > ocup_fin:
                            nuevos_segmentos.append((ocup_fin, seg_fin))

                segmentos_libres = nuevos_segmentos

            resultado.extend(segmentos_libres)

        # Merger segmentos adyacentes
        if resultado:
            resultado.sort()
            merged = [resultado[0]]
            for inicio, fin in resultado[1:]:
                if inicio <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], fin))
                else:
                    merged.append((inicio, fin))
            return merged

        return []

    @staticmethod
    def _construir_reserva_por_bloques(
        espacio_id: str,
        fecha_hora_inicio: datetime,
        duracion_requerida_min: int,
        empresa: Empresa,
        horizonte_dias: int,
        exigir_inicio_exacto: bool,
    ) -> ResultadoProgramacion:
        """Motor unico de reserva por bloques de 30 minutos."""
        if duracion_requerida_min <= 0:
            return ResultadoProgramacion(valido=False, error="Duracion requerida debe ser mayor que 0.")
        if duracion_requerida_min % BLOQUE_MINUTOS != 0:
            return ResultadoProgramacion(
                valido=False,
                error=f"La duracion debe ser multiplo de {BLOQUE_MINUTOS} minutos.",
            )

        if timezone.is_naive(fecha_hora_inicio):
            fecha_hora_inicio = timezone.make_aware(fecha_hora_inicio)

        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        inicio_operativo = CitasProgramacionService.normalizar_datetime_operativo(fecha_hora_inicio, empresa)
        hora_inicio_min = inicio_operativo.hour * 60 + inicio_operativo.minute

        if hora_inicio_min % BLOQUE_MINUTOS != 0:
            return ResultadoProgramacion(
                valido=False,
                error=f"La hora de inicio debe alinearse a bloques de {BLOQUE_MINUTOS} minutos.",
            )

        bloques_requeridos = duracion_requerida_min // BLOQUE_MINUTOS
        bloques_seleccionados: List[Tuple[datetime, int]] = []
        fecha_actual = inicio_operativo
        arranco_en_dia_1 = False

        for offset in range(horizonte_dias):
            ventanas_operativas = CitasProgramacionService.obtener_ventanas_operativas_dia(
                espacio_id=espacio_id,
                fecha=fecha_actual,
                empresa=empresa,
            )
            if not ventanas_operativas:
                fecha_actual += timedelta(days=1)
                continue

            ocupacion = CitasProgramacionService.obtener_ocupacion_espacio_dia(
                espacio_id=espacio_id,
                fecha=fecha_actual,
                empresa=empresa,
            )
            ventanas_libres = CitasProgramacionService.restar_ocupacion_ventanas(ventanas_operativas, ocupacion)
            if not ventanas_libres:
                fecha_actual += timedelta(days=1)
                continue

            inicio_minimo = hora_inicio_min if offset == 0 else None
            bloques_dia = CitasProgramacionService._bloques_inicio_desde_ventanas(
                ventanas_libres,
                inicio_minimo=inicio_minimo,
            )

            if offset == 0 and exigir_inicio_exacto and hora_inicio_min not in bloques_dia:
                return ResultadoProgramacion(
                    valido=False,
                    error=(
                        f"No es posible iniciar exactamente a las "
                        f"{inicio_operativo.strftime('%H:%M')} en {inicio_operativo.date()}."
                    ),
                )

            if offset == 0 and bloques_dia:
                arranco_en_dia_1 = True

            for bloque_inicio in bloques_dia:
                bloques_seleccionados.append((fecha_actual, bloque_inicio))
                if len(bloques_seleccionados) >= bloques_requeridos:
                    break

            if len(bloques_seleccionados) >= bloques_requeridos:
                break

            fecha_actual += timedelta(days=1)

        if exigir_inicio_exacto and not arranco_en_dia_1:
            return ResultadoProgramacion(
                valido=False,
                error=f"No hay bloques disponibles para iniciar en {inicio_operativo.date()}.",
            )

        if len(bloques_seleccionados) < bloques_requeridos:
            return ResultadoProgramacion(
                valido=False,
                fragmentado=len(bloques_seleccionados) > 1,
                segmentos=[],
                duracion_total_min=len(bloques_seleccionados) * BLOQUE_MINUTOS,
                error=f"No se pudo completar la reserva dentro de {horizonte_dias} dias.",
            )

        segmentos = []
        bloque_inicio_actual = bloques_seleccionados[0]
        bloque_fin_actual = bloque_inicio_actual[1] + BLOQUE_MINUTOS

        for fecha_bloque, inicio_bloque in bloques_seleccionados[1:]:
            misma_fecha = fecha_bloque.date() == bloque_inicio_actual[0].date()
            contiguo = misma_fecha and inicio_bloque == bloque_fin_actual
            if contiguo:
                bloque_fin_actual += BLOQUE_MINUTOS
                continue

            inicio_dt, fin_dt = CitasProgramacionService._minuto_operativo_a_dt_utc(
                bloque_inicio_actual[0],
                bloque_inicio_actual[1],
                bloque_fin_actual,
                tz_operativa,
            )
            segmentos.append(
                {
                    "inicio_dt": inicio_dt,
                    "fin_dt": fin_dt,
                    "duracion_min": bloque_fin_actual - bloque_inicio_actual[1],
                }
            )
            bloque_inicio_actual = (fecha_bloque, inicio_bloque)
            bloque_fin_actual = inicio_bloque + BLOQUE_MINUTOS

        inicio_dt, fin_dt = CitasProgramacionService._minuto_operativo_a_dt_utc(
            bloque_inicio_actual[0],
            bloque_inicio_actual[1],
            bloque_fin_actual,
            tz_operativa,
        )
        segmentos.append(
            {
                "inicio_dt": inicio_dt,
                "fin_dt": fin_dt,
                "duracion_min": bloque_fin_actual - bloque_inicio_actual[1],
            }
        )

        return ResultadoProgramacion(
            valido=True,
            fragmentado=len(segmentos) > 1,
            segmentos=segmentos,
            duracion_total_min=duracion_requerida_min,
            error=None,
        )

    @staticmethod
    def construir_reserva_canonica(
        espacio_id: str,
        fecha_inicio: datetime,
        hora_inicio_solicitada: int,
        duracion_requerida_min: int,
        empresa: Empresa,
        horizonte_dias: int = HORIZONTE_BUSQUEDA_DIAS,
    ) -> ResultadoProgramacion:
        """Construye reserva canonica desde la hora solicitada en bloques de 30 minutos."""
        fecha_hora_inicio = CitasProgramacionService.normalizar_datetime_operativo(fecha_inicio, empresa)
        fecha_hora_inicio = fecha_hora_inicio.replace(
            hour=hora_inicio_solicitada // 60,
            minute=hora_inicio_solicitada % 60,
            second=0,
            microsecond=0,
        )
        return CitasProgramacionService._construir_reserva_por_bloques(
            espacio_id=espacio_id,
            fecha_hora_inicio=fecha_hora_inicio,
            duracion_requerida_min=duracion_requerida_min,
            empresa=empresa,
            horizonte_dias=horizonte_dias,
            exigir_inicio_exacto=False,
        )

    @staticmethod
    def construir_reserva_desde_inicio_exacto(
        espacio_id: str,
        fecha_hora_inicio: datetime,
        duracion_requerida_min: int,
        empresa: Empresa,
        horizonte_dias: int = HORIZONTE_BUSQUEDA_DIAS,
    ) -> ResultadoProgramacion:
        """Valida y construye reserva exigiendo arranque exacto en el bloque solicitado."""
        return CitasProgramacionService._construir_reserva_por_bloques(
            espacio_id=espacio_id,
            fecha_hora_inicio=fecha_hora_inicio,
            duracion_requerida_min=duracion_requerida_min,
            empresa=empresa,
            horizonte_dias=horizonte_dias,
            exigir_inicio_exacto=True,
        )

    @staticmethod
    def encontrar_primer_inicio_disponible(
        espacio_id: str,
        fecha_hora_inicio: datetime,
        duracion_requerida_min: int,
        empresa: Empresa,
        horizonte_dias: int = HORIZONTE_BUSQUEDA_DIAS,
    ) -> Optional[Dict]:
        """
        Busca el PRIMER inicio exacto realmente disponible para una cita en un espacio.

        ALGORITMO MEJORADO (segÃºn correcciÃ³n de arquitectura):
        1. En el PRIMER DÃA candidato: 
           - Generar candidatos: hora solicitada + inicios de ventanas libres >= hora solicitada
           - Probar desde el mÃ¡s temprano que sea >= hora solicitada
           - NUNCA recommendar hora anterior a la solicitada en el primer dÃ­a
        2. En DÃAS POSTERIORES:
           - Generar candidatos desde inicio de ventanas operativas
           - Sin restricciÃ³n de hora
        3. Validar cada candidato con construir_reserva_desde_inicio_exacto()
        4. Retornar el primero que sea vÃ¡lido

        Args:
            espacio_id: UUID del espacio
            fecha_hora_inicio: Fecha/hora solicitada (inicio de bÃºsqueda)
            duracion_requerida_min: DuraciÃ³n requerida en minutos
            empresa: Empresa
            horizonte_dias: MÃ¡ximo de dÃ­as a buscar

        Returns:
            Dict con keys: inicio_dt, fin_dt, segmentos, fragmentado
            O None si no hay disponibilidad en el horizonte
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Asegurar datetime aware
        if timezone.is_naive(fecha_hora_inicio):
            fecha_hora_inicio = timezone.make_aware(fecha_hora_inicio)
        
        # Normalizar a timezone operativa para el procesamiento
        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        fecha_hora_inicio_op = CitasProgramacionService.normalizar_datetime_operativo(
            fecha_hora_inicio, empresa
        )
        hora_solicitada_min = fecha_hora_inicio_op.hour * 60 + fecha_hora_inicio_op.minute
        
        logger.info(
            f"[encontrar_primer_inicio_disponible] Buscando primer inicio desde "
            f"{fecha_hora_inicio_op} (hora={hora_solicitada_min}min), "
            f"duraciÃ³n={duracion_requerida_min}min"
        )

        candidatos = []
        fecha_base = fecha_hora_inicio_op
        
        # Generar candidatos en el horizonte
        for offset in range(horizonte_dias):
            fecha_actual = fecha_base + timedelta(days=offset)
            
            ventanas_operativas = CitasProgramacionService.obtener_ventanas_operativas_dia(
                espacio_id=espacio_id,
                fecha=fecha_actual,
                empresa=empresa,
            )

            if not ventanas_operativas:
                logger.debug(f"[encontrar_primer_inicio_disponible] DÃ­a {offset} sin ventanas operativas")
                continue

            ocupacion = CitasProgramacionService.obtener_ocupacion_espacio_dia(
                espacio_id=espacio_id,
                fecha=fecha_actual,
                empresa=empresa,
            )

            ventanas_libres = CitasProgramacionService.restar_ocupacion_ventanas(
                ventanas_operativas, ocupacion
            )

            if offset == 0:
                # DÍA 1: solo candidatos en bloques >= hora solicitada
                bloques_dia = CitasProgramacionService._bloques_inicio_desde_ventanas(
                    ventanas_libres,
                    inicio_minimo=hora_solicitada_min,
                )
            else:
                # DÍAS POSTERIORES: todos los bloques de ventanas libres
                bloques_dia = CitasProgramacionService._bloques_inicio_desde_ventanas(
                    ventanas_libres
                )

            for bloque_inicio in bloques_dia:
                candidatos.append((fecha_actual.date(), bloque_inicio))

        # Deduplicar y ordenar
        candidatos = sorted(set(candidatos), key=lambda x: (x[0], x[1]))

        logger.info(
            f"[encontrar_primer_inicio_disponible] Total candidatos deduplicados: {len(candidatos)}"
        )

        # Probar cada candidato con el validador estricto
        for fecha_candidata, minuto_candidato in candidatos:
            # Reconvertir a datetime en timezone operativa
            dt_candidato_op = tz_operativa.localize(
                datetime.combine(
                    fecha_candidata,
                    datetime.min.time().replace(
                        hour=minuto_candidato // 60,
                        minute=minuto_candidato % 60
                    )
                )
            )
            # Convertir a UTC para validaciÃ³n
            dt_candidato_utc = dt_candidato_op.astimezone(timezone.utc)

            # Validar temporalmente (no pasado)
            valido_temp, _ = CitasProgramacionService.validar_inicio_no_pasado(
                dt_candidato_utc,
                empresa,
            )
            if not valido_temp:
                logger.debug(
                    f"[encontrar_primer_inicio_disponible] Candidato {dt_candidato_op} "
                    f"rechazado: inicio en el pasado"
                )
                continue

            # Validar exactitud con mÃ©todo estricto
            resultado = CitasProgramacionService.construir_reserva_desde_inicio_exacto(
                espacio_id=espacio_id,
                fecha_hora_inicio=dt_candidato_utc,
                duracion_requerida_min=duracion_requerida_min,
                empresa=empresa,
                horizonte_dias=horizonte_dias,
            )

            if resultado.valido and resultado.segmentos:
                logger.info(
                    f"[encontrar_primer_inicio_disponible] SUCCESS - "
                    f"Primer horario disponible: {resultado.segmentos[0]['inicio_dt']}"
                )
                return {
                    "inicio_dt": resultado.segmentos[0]["inicio_dt"],
                    "fin_dt": resultado.segmentos[-1]["fin_dt"],
                    "segmentos": resultado.segmentos,
                    "fragmentado": resultado.fragmentado,
                }

        logger.warning(
            f"[encontrar_primer_inicio_disponible] NO ENCONTRADO - "
            f"Sin disponibilidad en {horizonte_dias} dÃ­as"
        )
        return None

    @staticmethod
    def construir_estado_inicial_cita(usuario_creador: Usuario) -> str:
        """
        Determina el estado inicial de una cita segÃºn el rol del creador.

        Regla:
        - Si ADMIN o ASESOR_SERVICIO â†’ PROGRAMADA
        - Si USUARIO â†’ PENDIENTE_APROBACION

        Args:
            usuario_creador: Usuario que crea la cita

        Returns:
            Estado (como string) de EstadoCita
        """
        rol_nombre = usuario_creador.rol.nombre if usuario_creador.rol else "USUARIO"

        if rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]:
            return EstadoCita.PROGRAMADA

        return EstadoCita.PENDIENTE_APROBACION

