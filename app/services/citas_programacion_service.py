"""
Servicio de Programación de Citas - CU18

Centraliza toda la lógica de:
  - Validación temporal (fecha/hora no en el pasado)
  - Cálculo de disponibilidad de espacios
  - Fragmentación de reservas (intra-día y multi-día)
  - Construcción de segmentos canónicos
  
Propósito: Ser la fuente de verdad del backend para programación de citas.
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Optional
from django.utils import timezone
from django.db.models import Q

from app.models import (
    Cita,
    CitaEspacioSegmento,
    EspacioTrabajo,
    HorarioEspacioTrabajo,
    Empresa,
    EstadoCita,
    Usuario,
)


class ResultadoProgramacion:
    """Resultado de un intento de programación."""

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
        """Convierte a diccionario para serialización."""
        return {
            "valido": self.valido,
            "fragmentado": self.fragmentado,
            "segmentos": self.segmentos,
            "duracion_total_min": self.duracion_total_min,
            "error": self.error,
        }


class CitasProgramacionService:
    """Servicio de lógica de programación de citas."""

    HORIZONTE_BUSQUEDA_DIAS = 30
    BUFFER_MINUTO_HOY = 5

    @staticmethod
    def obtener_timezone_operativa(empresa: Empresa):
        """
        Obtiene la timezone operativa del negocio asociado a la empresa.
        
        Fallback: America/La_Paz si no está configurada.
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
        Valida que fecha_hora_inicio no esté en el pasado.

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
            # Si es fecha futura pero hora está en el pasado
            if fecha_hora_inicio < ahora:
                return False, "No puedes solicitar una cita en el pasado."

        return True, None

    @staticmethod
    def obtener_ventanas_operativas_dia(
        espacio_id: str, fecha: datetime, empresa: Empresa
    ) -> List[Tuple[int, int]]:
        """
        Obtiene ventanas operativas de un espacio para un día específico.

        Devuelve lista de tuplas (hora_inicio_min, hora_fin_min) en minutos desde medianoche.
        Usa HorarioEspacioTrabajo.
        
        CORRECCIÓN: Normaliza fecha a timezone operativa antes de calcular día de semana.

        Args:
            espacio_id: UUID del espacio
            fecha: Fecha (solo se usa el día de la semana, será normalizada a tz operativa)
            empresa: Empresa (para validar pertenencia)

        Returns:
            [(hora_inicio_minutos, hora_fin_minutos), ...] en minutos de tz operativa
            Ordenado por hora inicio.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # CORRECCIÓN: Normalizar fecha a timezone operativa
        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        fecha_operativa = CitasProgramacionService.normalizar_datetime_operativo(fecha, empresa)
        
        # Calcular día de la semana EN TIMEZONE OPERATIVA (0 = Lunes, 6 = Domingo)
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
                f"[obtener_ventanas_operativas_dia] Horario: {h.hora_inicio} → {h.hora_fin} "
                f"({inicio_min}min → {fin_min}min)"
            )

        return ventanas


    @staticmethod
    def obtener_ocupacion_espacio_dia(
        espacio_id: str, fecha: datetime, empresa: Empresa
    ) -> List[Tuple[int, int]]:
        """
        Obtiene intervalos ocupados de un espacio para un día específico.

        Extrae de CitaEspacioSegmento con citas activas.
        CORRECCIÓN: Normaliza datetimes a timezone operativa antes de calcular minutos.

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

        # Convertir fecha a timezone operativa para determinar límites del día
        fecha_operativa = fecha.astimezone(tz_operativa) if fecha.tzinfo else fecha

        # Inicio y fin del día en timezone operativa
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
            f"rango_operativo={inicio_dia_operativo} → {fin_dia_operativo}, "
            f"rango_utc={inicio_dia_utc} → {fin_dia_utc}"
        )

        # Query en UTC (como está almacenado en BD)
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
            # CORRECCIÓN CRÍTICA: Normalizar a timezone operativa antes de extraer hora/minuto
            inicio_operativo = seg.inicio_programado.astimezone(tz_operativa)
            fin_operativo = seg.fin_programado.astimezone(tz_operativa)

            # Solo incluir si la porción en timezone operativa está dentro del día
            # (maneja segmentos que cruzan medianoche)
            if inicio_operativo.date() <= fecha_operativa.date():
                if fin_operativo.date() >= fecha_operativa.date():
                    # Truncar al rango del día si es necesario
                    inicio_min = max(inicio_operativo.hour * 60 + inicio_operativo.minute, 0)
                    fin_min = min(fin_operativo.hour * 60 + fin_operativo.minute, 24 * 60)
                    
                    ocupacion.append((inicio_min, fin_min))
                    logger.debug(
                        f"[obtener_ocupacion_espacio_dia] Segmento (UTC: {seg.inicio_programado} → {seg.fin_programado}) "
                        f"→ Operativo: {inicio_operativo} → {fin_operativo} "
                        f"→ Minutaje: {inicio_min}min → {fin_min}min"
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
    def construir_reserva_desde_inicio_exacto(
        espacio_id: str,
        fecha_hora_inicio: datetime,
        duracion_requerida_min: int,
        empresa: Empresa,
        horizonte_dias: int = 30,
    ) -> "ResultadoProgramacion":
        """
        Valida si una cita puede comenzar EXACTAMENTE en fecha_hora_inicio.
        
        Reglas:
        - La hora solicitada debe caer dentro de una ventana libre real del primer día
        - Si no cae dentro de una ventana libre, retorna inválido
        - Si sí cae dentro, reutiliza construir_reserva_canonica para completar
          la cita fragmentando si hace falta en el mismo día y días siguientes
        """
        if duracion_requerida_min <= 0:
            return ResultadoProgramacion(
                valido=False,
                error="Duración requerida debe ser mayor que 0."
            )

        if timezone.is_naive(fecha_hora_inicio):
            fecha_hora_inicio = timezone.make_aware(fecha_hora_inicio)

        # Obtener ventanas libres reales del primer día
        ventanas_operativas = CitasProgramacionService.obtener_ventanas_operativas_dia(
            espacio_id=espacio_id,
            fecha=fecha_hora_inicio,
            empresa=empresa,
        )

        if not ventanas_operativas:
            return ResultadoProgramacion(
                valido=False,
                error="El espacio no tiene horarios operativos para la fecha solicitada."
            )

        ocupacion = CitasProgramacionService.obtener_ocupacion_espacio_dia(
            espacio_id=espacio_id,
            fecha=fecha_hora_inicio,
            empresa=empresa,
        )

        ventanas_libres = CitasProgramacionService.restar_ocupacion_ventanas(
            ventanas_operativas,
            ocupacion,
        )

        hora_inicio_min = fecha_hora_inicio.hour * 60 + fecha_hora_inicio.minute

        # La cita debe poder arrancar EXACTAMENTE dentro de una ventana libre
        cae_en_ventana_libre = any(
            inicio <= hora_inicio_min < fin
            for inicio, fin in ventanas_libres
        )

        if not cae_en_ventana_libre:
            return ResultadoProgramacion(
                valido=False,
                error="La cita no puede iniciar exactamente en la hora solicitada."
            )

        # Si sí cae dentro de ventana libre, usar el motor canónico existente
        return CitasProgramacionService.construir_reserva_canonica(
            espacio_id=espacio_id,
            fecha_inicio=fecha_hora_inicio,
            hora_inicio_solicitada=hora_inicio_min,
            duracion_requerida_min=duracion_requerida_min,
            empresa=empresa,
            horizonte_dias=horizonte_dias,
        )

    @staticmethod
    def construir_reserva_canonica(
        espacio_id: str,
        fecha_inicio: datetime,
        hora_inicio_solicitada: int,  # minutos desde medianoche
        duracion_requerida_min: int,
        empresa: Empresa,
        horizonte_dias: int = HORIZONTE_BUSQUEDA_DIAS,
    ) -> ResultadoProgramacion:
        """
        Construye una reserva canónica respetando:
        1. Ventanas operativas reales
        2. Ocupación existente
        3. Fragmentación intra-día antes de pasar al siguiente día
        4. Continuidad multi-día si es necesario

        Algoritmo:
        1. Para el día inicial:
           - Obtener ventanas operativas
           - Restar ocupación
           - Filtrar ventanas donde fin > hora_inicio_solicitada
           - Consumir tiempo en esas ventanas
        2. Si duracion_requerida aún > 0 y hay más días:
           - Pasar al siguiente día
           - Repetir desde ventana 1 del día
        3. Continuar hasta completar o exceder horizonte

        Args:
            espacio_id: UUID del espacio
            fecha_inicio: Fecha de inicio deseada
            hora_inicio_solicitada: Hora de inicio en minutos (ej: 11:00 = 660)
            duracion_requerida_min: Duración requerida en minutos
            empresa: Empresa
            horizonte_dias: Máximo de días a buscar

        Returns:
            ResultadoProgramacion con segmentos o error
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"[construir_reserva_canonica] INICIO - espacio_id={espacio_id}, fecha_inicio={fecha_inicio}, hora_inicio_solicitada={hora_inicio_solicitada}, duracion={duracion_requerida_min}min")
        
        if duracion_requerida_min <= 0:
            return ResultadoProgramacion(
                valido=False,
                error="Duración requerida debe ser mayor que 0."
            )

        segmentos = []
        duracion_restante = duracion_requerida_min
        fecha_actual = fecha_inicio
        es_primer_dia = True
        hora_solicitada_usada = False  # Track si ya usamos la hora solicitada
        dias_buscados = 0

        while duracion_restante > 0 and dias_buscados < horizonte_dias:
            dias_buscados += 1

            # Obtener ventanas operativas del día
            ventanas_operativas = CitasProgramacionService.obtener_ventanas_operativas_dia(
                espacio_id, fecha_actual, empresa
            )

            if not ventanas_operativas:
                # Sin horarios operativos, pasar al siguiente día
                fecha_actual += timedelta(days=1)
                es_primer_dia = False
                continue

            # Obtener ocupación del día
            ocupacion = CitasProgramacionService.obtener_ocupacion_espacio_dia(
                espacio_id, fecha_actual, empresa
            )

            logger.debug(f"[construir_reserva_canonica] Ventanas operativas: {ventanas_operativas}")
            logger.debug(f"[construir_reserva_canonica] Ocupacion: {ocupacion}")

            # Restar ocupación de ventanas
            ventanas_libres = CitasProgramacionService.restar_ocupacion_ventanas(
                ventanas_operativas, ocupacion
            )

            logger.debug(f"[construir_reserva_canonica] Ventanas libres después de restar ocupacion: {ventanas_libres}")

            if not ventanas_libres:
                # Sin espacio libre este día
                fecha_actual += timedelta(days=1)
                es_primer_dia = False
                continue

            # Procesar ventanas libres
            for ventana_inicio, ventana_fin in ventanas_libres:
                if duracion_restante <= 0:
                    break

                if es_primer_dia and not hora_solicitada_usada:
                    # En el primer día Y no hemos usado la hora solicitada aún,
                    # verificar si esta ventana contiene la hora solicitada
                    if hora_inicio_solicitada < ventana_inicio:
                        # La hora solicitada está ANTES de esta ventana, skipear
                        continue
                    
                    if hora_inicio_solicitada >= ventana_fin:
                        # La hora solicitada está DESPUÉS de esta ventana, skipear
                        continue
                    
                    # Está dentro de la ventana, usar exactamente lo solicitado
                    inicio_efectivo = hora_inicio_solicitada
                    hora_solicitada_usada = True
                else:
                    # En días siguientes o después de usar la hora solicitada,
                    # empezar desde el principio de la ventana
                    inicio_efectivo = ventana_inicio

                # Calcular minutos disponibles en esta ventana
                minutos_disponibles = ventana_fin - inicio_efectivo
                minutos_usar = min(minutos_disponibles, duracion_restante)

                if minutos_usar <= 0:
                    continue

                # Crear datetime para inicio y fin
                inicio_min_del_dia = inicio_efectivo
                fin_min_del_dia = inicio_efectivo + minutos_usar

                hora_inicio = inicio_min_del_dia // 60
                min_inicio = inicio_min_del_dia % 60
                hora_fin = fin_min_del_dia // 60
                min_fin = fin_min_del_dia % 60

                inicio_dt = timezone.make_aware(
                    datetime.combine(
                        fecha_actual.date(),
                        datetime.min.time().replace(hour=hora_inicio, minute=min_inicio)
                    )
                )
                fin_dt = timezone.make_aware(
                    datetime.combine(
                        fecha_actual.date(),
                        datetime.min.time().replace(hour=hora_fin, minute=min_fin)
                    )
                )

                segmentos.append({
                    "inicio_dt": inicio_dt,
                    "fin_dt": fin_dt,
                    "duracion_min": minutos_usar,
                })

                duracion_restante -= minutos_usar

            # Pasar al siguiente día
            fecha_actual += timedelta(days=1)
            es_primer_dia = False

        if duracion_restante > 0:
            return ResultadoProgramacion(
                valido=False,
                fragmentado=len(segmentos) > 1,
                segmentos=segmentos,
                duracion_total_min=duracion_requerida_min - duracion_restante,
                error=f"No se pudo completar la reserva dentro de {horizonte_dias} días. "
                f"Se cubrieron solo {duracion_requerida_min - duracion_restante}/{duracion_requerida_min} minutos.",
            )

        fragmentado = len(segmentos) > 1

        return ResultadoProgramacion(
            valido=True,
            fragmentado=fragmentado,
            segmentos=segmentos,
            duracion_total_min=duracion_requerida_min,
            error=None,
        )

    @staticmethod
    def construir_reserva_desde_inicio_exacto(
        espacio_id: str,
        fecha_hora_inicio: datetime,
        duracion_requerida_min: int,
        empresa: Empresa,
        horizonte_dias: int = HORIZONTE_BUSQUEDA_DIAS,
    ) -> ResultadoProgramacion:
        """
        Construye una reserva EXIGIENDO que inicie exactamente a la hora especificada.

        VALIDADOR ESTRICTO: No reschedule automáticamente. Solo valida si es posible 
        iniciar exactamente a la hora solicitada sin gaps.

        Algoritmo:
        1. Extrae hora_inicio_solicitada del datetime
        2. En el día especificado:
           - Obtiene ventanas operativas
           - Resta ocupación
           - Verifica si hay ventana libre que contenga la hora exacta
           - Si NO → retorna error inmediato (NO intenta otros días)
           - Si SÍ → construye reserva desde la hora exacta hasta completar duracion
        3. Si duracion se completa en el día 1 → SUCCESS
        4. Si duracion no se completa en día 1:
           - Continúa a días posteriores SOLO si día 1 inició correctamente
           - Completa en días siguientes sin restricción de hora

        Args:
            espacio_id: UUID del espacio
            fecha_hora_inicio: Fecha Y hora exacta de inicio deseada (será normalizada a tz operativa)
            duracion_requerida_min: Duración requerida en minutos
            empresa: Empresa
            horizonte_dias: Máximo de días a buscar (para continuación)

        Returns:
            ResultadoProgramacion:
            - valido=True + segmentos: reserva construida con inicio exacto
            - valido=False + error: no fue posible iniciar exactamente en esa hora
        """
        import logging
        logger = logging.getLogger(__name__)
        
        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        
        # Normalizar fecha_hora_inicio a timezone operativa
        fecha_hora_inicio_op = CitasProgramacionService.normalizar_datetime_operativo(
            fecha_hora_inicio, empresa
        )
        
        # Extraer hora solicitada en minutos
        hora_inicio_solicitada = fecha_hora_inicio_op.hour * 60 + fecha_hora_inicio_op.minute
        
        logger.info(
            f"[construir_reserva_desde_inicio_exacto] STRICT - espacio_id={espacio_id}, "
            f"fecha_hora_inicio_operativa={fecha_hora_inicio_op}, "
            f"hora_exacta={hora_inicio_solicitada}min, duracion={duracion_requerida_min}min"
        )

        if duracion_requerida_min <= 0:
            return ResultadoProgramacion(
                valido=False,
                error="Duración requerida debe ser mayor que 0."
            )

        segmentos = []
        duracion_restante = duracion_requerida_min
        fecha_actual = fecha_hora_inicio_op
        es_primer_dia = True
        dias_buscados = 0
        
        # ============ DÍA 1: VALIDACIÓN ESTRICTA ============
        dias_buscados += 1
        
        # Obtener ventanas operativas del día 1
        ventanas_operativas = CitasProgramacionService.obtener_ventanas_operativas_dia(
            espacio_id, fecha_actual, empresa
        )

        if not ventanas_operativas:
            logger.warning(
                f"[construir_reserva_desde_inicio_exacto] Día 1 sin horarios operativos"
            )
            return ResultadoProgramacion(
                valido=False,
                error=f"No hay horarios operativos disponibles para {fecha_actual.date()}"
            )

        # Obtener ocupación del día 1
        ocupacion = CitasProgramacionService.obtener_ocupacion_espacio_dia(
            espacio_id, fecha_actual, empresa
        )

        logger.debug(
            f"[construir_reserva_desde_inicio_exacto] Día 1 - "
            f"Ventanas operativas: {ventanas_operativas}, Ocupacion: {ocupacion}"
        )

        # Restar ocupación de ventanas
        ventanas_libres = CitasProgramacionService.restar_ocupacion_ventanas(
            ventanas_operativas, ocupacion
        )

        logger.debug(
            f"[construir_reserva_desde_inicio_exacto] Día 1 - "
            f"Ventanas libres: {ventanas_libres}"
        )

        if not ventanas_libres:
            logger.warning(
                f"[construir_reserva_desde_inicio_exacto] Día 1 completamente ocupado"
            )
            return ResultadoProgramacion(
                valido=False,
                error=f"El espacio está completamente ocupado en {fecha_actual.date()} "
                      f"a la hora solicitada."
            )

        # VALIDACIÓN ESTRICTA: ¿EXISTE ventana que contenga hora_inicio_solicitada?
        ventana_contiene_hora_exacta = None
        for vent_inicio, vent_fin in ventanas_libres:
            if vent_inicio <= hora_inicio_solicitada < vent_fin:
                ventana_contiene_hora_exacta = (vent_inicio, vent_fin)
                break
        
        if ventana_contiene_hora_exacta is None:
            logger.warning(
                f"[construir_reserva_desde_inicio_exacto] Hora exacta {hora_inicio_solicitada}min "
                f"NO DISPONIBLE en Día 1. Ventanas libres: {ventanas_libres}"
            )
            return ResultadoProgramacion(
                valido=False,
                error=f"No es posible iniciar exactamente a las {fecha_hora_inicio_op.strftime('%H:%M')} "
                      f"en {fecha_actual.date()}. Espacio ocupado."
            )

        # ============ DÍA 1: CONSTRUCCIÓN DESDE HORA EXACTA ============
        
        # Usar hora exacta en la ventana que la contiene
        inicio_efectivo = hora_inicio_solicitada
        vent_inicio, vent_fin = ventana_contiene_hora_exacta
        
        # Calcular minutos disponibles hasta fin de la ventana
        minutos_disponibles = vent_fin - inicio_efectivo
        minutos_usar = min(minutos_disponibles, duracion_restante)
        
        if minutos_usar <= 0:
            logger.warning(
                f"[construir_reserva_desde_inicio_exacto] Minutos = 0 en ventana"
            )
            return ResultadoProgramacion(
                valido=False,
                error="No hay tiempo suficiente en la ventana para la hora solicitada."
            )

        # Crear datetime para inicio y fin (Día 1)
        inicio_min_del_dia = inicio_efectivo
        fin_min_del_dia = inicio_efectivo + minutos_usar

        hora_inicio = inicio_min_del_dia // 60
        min_inicio = inicio_min_del_dia % 60
        hora_fin = fin_min_del_dia // 60
        min_fin = fin_min_del_dia % 60

        # Crear datetimes EN TIMEZONE OPERATIVA, luego convertir a UTC para BD
        inicio_dt_operativo = tz_operativa.localize(
            datetime.combine(
                fecha_actual.date(),
                datetime.min.time().replace(hour=hora_inicio, minute=min_inicio)
            )
        )
        fin_dt_operativo = tz_operativa.localize(
            datetime.combine(
                fecha_actual.date(),
                datetime.min.time().replace(hour=hora_fin, minute=min_fin)
            )
        )

        # Convertir a UTC para storage en BD
        inicio_dt_utc = inicio_dt_operativo.astimezone(timezone.utc)
        fin_dt_utc = fin_dt_operativo.astimezone(timezone.utc)

        segmentos.append({
            "inicio_dt": inicio_dt_utc,
            "fin_dt": fin_dt_utc,
            "duracion_min": minutos_usar,
        })

        duracion_restante -= minutos_usar
        
        logger.debug(
            f"[construir_reserva_desde_inicio_exacto] Día 1 asignado: "
            f"{inicio_dt_operativo} → {fin_dt_operativo} ({minutos_usar}min), "
            f"restante={duracion_restante}min"
        )

        # ============ DÍAS POSTERIORES: SIN RESTRICCIÓN DE HORA ============
        
        fecha_actual += timedelta(days=1)
        
        while duracion_restante > 0 and dias_buscados < horizonte_dias:
            dias_buscados += 1

            # Obtener ventanas operativas del día
            ventanas_operativas = CitasProgramacionService.obtener_ventanas_operativas_dia(
                espacio_id, fecha_actual, empresa
            )

            if not ventanas_operativas:
                fecha_actual += timedelta(days=1)
                continue

            # Obtener ocupación del día
            ocupacion = CitasProgramacionService.obtener_ocupacion_espacio_dia(
                espacio_id, fecha_actual, empresa
            )

            # Restar ocupación de ventanas
            ventanas_libres = CitasProgramacionService.restar_ocupacion_ventanas(
                ventanas_operativas, ocupacion
            )

            if not ventanas_libres:
                fecha_actual += timedelta(days=1)
                continue

            # Procesar ventanas libres (SIN restricción de hora en días posteriores)
            for ventana_inicio, ventana_fin in ventanas_libres:
                if duracion_restante <= 0:
                    break

                inicio_efectivo = ventana_inicio
                minutos_disponibles = ventana_fin - inicio_efectivo
                minutos_usar = min(minutos_disponibles, duracion_restante)

                if minutos_usar <= 0:
                    continue

                # Crear datetime para inicio y fin
                inicio_min_del_dia = inicio_efectivo
                fin_min_del_dia = inicio_efectivo + minutos_usar

                hora_inicio = inicio_min_del_dia // 60
                min_inicio = inicio_min_del_dia % 60
                hora_fin = fin_min_del_dia // 60
                min_fin = fin_min_del_dia % 60

                inicio_dt_operativo = tz_operativa.localize(
                    datetime.combine(
                        fecha_actual.date(),
                        datetime.min.time().replace(hour=hora_inicio, minute=min_inicio)
                    )
                )
                fin_dt_operativo = tz_operativa.localize(
                    datetime.combine(
                        fecha_actual.date(),
                        datetime.min.time().replace(hour=hora_fin, minute=min_fin)
                    )
                )

                inicio_dt_utc = inicio_dt_operativo.astimezone(timezone.utc)
                fin_dt_utc = fin_dt_operativo.astimezone(timezone.utc)

                segmentos.append({
                    "inicio_dt": inicio_dt_utc,
                    "fin_dt": fin_dt_utc,
                    "duracion_min": minutos_usar,
                })

                duracion_restante -= minutos_usar

            fecha_actual += timedelta(days=1)

        if duracion_restante > 0:
            logger.warning(
                f"[construir_reserva_desde_inicio_exacto] Duración incompleta: "
                f"{duracion_requerida_min - duracion_restante}/{duracion_requerida_min}min"
            )
            return ResultadoProgramacion(
                valido=False,
                fragmentado=len(segmentos) > 1,
                segmentos=segmentos,
                duracion_total_min=duracion_requerida_min - duracion_restante,
                error=f"Se requirieron más de {horizonte_dias} días para completar la reserva."
            )

        fragmentado = len(segmentos) > 1

        logger.info(
            f"[construir_reserva_desde_inicio_exacto] SUCCESS - "
            f"Reserva construida: {len(segmentos)} segmento(s), "
            f"fragmentado={fragmentado}, duracion_total={duracion_requerida_min}min"
        )

        return ResultadoProgramacion(
            valido=True,
            fragmentado=fragmentado,
            segmentos=segmentos,
            duracion_total_min=duracion_requerida_min,
            error=None,
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

        ALGORITMO MEJORADO (según corrección de arquitectura):
        1. En el PRIMER DÍA candidato: 
           - Generar candidatos: hora solicitada + inicios de ventanas libres >= hora solicitada
           - Probar desde el más temprano que sea >= hora solicitada
           - NUNCA recommendar hora anterior a la solicitada en el primer día
        2. En DÍAS POSTERIORES:
           - Generar candidatos desde inicio de ventanas operativas
           - Sin restricción de hora
        3. Validar cada candidato con construir_reserva_desde_inicio_exacto()
        4. Retornar el primero que sea válido

        Args:
            espacio_id: UUID del espacio
            fecha_hora_inicio: Fecha/hora solicitada (inicio de búsqueda)
            duracion_requerida_min: Duración requerida en minutos
            empresa: Empresa
            horizonte_dias: Máximo de días a buscar

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
            f"duración={duracion_requerida_min}min"
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
                logger.debug(f"[encontrar_primer_inicio_disponible] Día {offset} sin ventanas operativas")
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
                # DÍA 1: RESTRICCIÓN - No agregar candidatos anteriores a hora solicitada
                # 1. Hora solicitada misma (si está en ventana libre)
                for vent_inicio, vent_fin in ventanas_libres:
                    if vent_inicio <= hora_solicitada_min < vent_fin:
                        candidatos.append((fecha_actual.date(), hora_solicitada_min))
                        break

                # 2. Inicios de ventanas libres >= hora solicitada
                for vent_inicio, _ in ventanas_libres:
                    if vent_inicio >= hora_solicitada_min:
                        candidatos.append((fecha_actual.date(), vent_inicio))

                # 3. Fin de intervalos ocupados >= hora solicitada
                for _, fin_ocupado in ocupacion:
                    if fin_ocupado >= hora_solicitada_min:
                        candidatos.append((fecha_actual.date(), fin_ocupado))

                logger.debug(
                    f"[encontrar_primer_inicio_disponible] Día 0 - "
                    f"Candidatos (solo >= {hora_solicitada_min}min): {len(candidatos)}"
                )
            else:
                # DÍAS POSTERIORES: SIN RESTRICCIÓN
                # 1. Inicios de ventanas libres
                for vent_inicio, _ in ventanas_libres:
                    candidatos.append((fecha_actual.date(), vent_inicio))

                # 2. Fin de intervalos ocupados
                for _, fin_ocupado in ocupacion:
                    candidatos.append((fecha_actual.date(), fin_ocupado))

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
            # Convertir a UTC para validación
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

            # Validar exactitud con método estricto
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
            f"Sin disponibilidad en {horizonte_dias} días"
        )
        return None

    @staticmethod
    def construir_estado_inicial_cita(usuario_creador: Usuario) -> str:
        """
        Determina el estado inicial de una cita según el rol del creador.

        Regla:
        - Si ADMIN o ASESOR_SERVICIO → PROGRAMADA
        - Si USUARIO → PENDIENTE_APROBACION

        Args:
            usuario_creador: Usuario que crea la cita

        Returns:
            Estado (como string) de EstadoCita
        """
        rol_nombre = usuario_creador.rol.nombre if usuario_creador.rol else "USUARIO"

        if rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]:
            return EstadoCita.PROGRAMADA

        return EstadoCita.PENDIENTE_APROBACION
