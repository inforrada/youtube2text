import json
import os
import re
import sys
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from youtube_transcript_api import YouTubeTranscriptApi

# Definimos el esquema de salida estructurada
class ShortSegment(BaseModel):
    titulo: str = Field(description="Título atractivo del Short")
    gancho_primeros_3_seg: str = Field(description="La frase inicial que retiene a la audiencia")
    start_time: str = Field(description="Tiempo de inicio en formato mm:ss")
    end_time: str = Field(description="Tiempo de fin en formato mm:ss")
    start_seconds: int = Field(description="Segundo exacto de inicio")
    end_seconds: int = Field(description="Segundo exacto de fin")
    por_que_es_viral: str = Field(description="Motivo del potencial viral (controversia, aprendizaje rápido, sorpresa)")

class RespuestaShorts(BaseModel):
    shorts: list[ShortSegment]

def extraer_video_id(url_o_id: str) -> str:
    patron = r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})"
    coincidencia = re.search(patron, url_o_id)
    return coincidencia.group(1) if coincidencia else url_o_id

def segundos_a_mmss(segundos: float) -> str:
    """Convierte segundos a formato mm:ss."""
    m, s = divmod(int(segundos), 60)
    return f"{m:02d}:{s:02d}"

def obtener_transcripcion_con_tiempos(video_id: str) -> str:
    print(f"📥 Obteniendo subtítulos y marcas de tiempo de {video_id}...")
    try:
        # Compatibilidad con versión nueva (v1.x: instancia + fetch)
        if hasattr(YouTubeTranscriptApi, 'fetch') or hasattr(YouTubeTranscriptApi(), 'fetch'):
            yt_api = YouTubeTranscriptApi()
            transcript = yt_api.fetch(video_id, languages=['es', 'es-ES'])
            lineas = []
            for bloque in transcript:
                start = getattr(bloque, 'start', None) if hasattr(bloque, 'start') else bloque.get('start', 0)
                text = getattr(bloque, 'text', None) if hasattr(bloque, 'text') else bloque.get('text', '')
                seg = int(start)
                mmss = segundos_a_mmss(seg)
                lineas.append(f"[{seg}s | {mmss}] {text.strip()}")
            return "\n".join(lineas)

        # Compatibilidad con versión clásica (<1.0: get_transcript)
        elif hasattr(YouTubeTranscriptApi, 'get_transcript'):
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'es-ES'])
            lineas = []
            for t in transcript:
                seg = int(t['start'])
                mmss = segundos_a_mmss(seg)
                lineas.append(f"[{seg}s | {mmss}] {t['text'].strip()}")
            return "\n".join(lineas)

        else:
            raise RuntimeError("No se encontró ningún método válido en YouTubeTranscriptApi.")

    except Exception as e:
        raise RuntimeError(f"Error al obtener subtítulos de YouTube: {e}")

def guardar_transcripcion_disco(video_id: str, texto_con_tiempos: str) -> str:
    """Vuelca la transcripción con tiempos a un archivo de texto plano."""
    nombre_archivo = f"transcripcion_tiempos_{video_id}.txt"
    with open(nombre_archivo, "w", encoding="utf-8") as f:
        f.write(texto_con_tiempos)
    print(f"💾 Transcripción con tiempos guardada en disco: {nombre_archivo}")
    return nombre_archivo

def detectar_momentos_virales(transcript_con_marcas: str) -> RespuestaShorts:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "No se detectó la variable de entorno GEMINI_API_KEY.\n"
            "Puedes usar el archivo generado manualmente en Google AI Studio o configurar la clave en tu terminal."
        )

    client = genai.Client()
    print("🧠 Analizando la transcripción para detectar los mejores cortes...")

    prompt = f"""
    Actúa como un editor profesional especializado en YouTube Shorts, Reels y TikTok.
    Analiza la siguiente transcripción con marcas de tiempo en segundos.

    Identifica los 2 o 3 mejores fragmentos para convertirlos en Shorts de alto impacto.

    Criterios indispensables para cada Short:
    1. **Duración:** Entre 30 y 60 segundos de duración total.
    2. **Gancho inmediato:** Debe comenzar con una frase potente (pregunta, afirmación controvertida, dato sorprendente) en los primeros 3 segundos.
    3. **Autonomía:** El corte debe tener sentido completo por sí mismo (principio, desarrollo y remate).
    4. **Precisión:** Utiliza las marcas en segundos [Xs] de la transcripción para definir el punto de corte inicial y final exacto.

    Transcripción con marcas de tiempo:
    {transcript_con_marcas}
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RespuestaShorts,
            temperature=0.2,
        ),
    )

    return RespuestaShorts.model_validate_json(response.text)

def main():
    if len(sys.argv) > 1:
        entrada = sys.argv[1].strip()
    else:
        entrada = input("Pega la URL o ID del vídeo: ").strip()

    if not entrada:
        print("Entrada vacía. Abortando.")
        return

    video_id = extraer_video_id(entrada)

    # 1. Obtener transcripción con tiempos y guardarla en disco
    try:
        transcript_marcas = obtener_transcripcion_con_tiempos(video_id)
        ruta_archivo = guardar_transcripcion_disco(video_id, transcript_marcas)
    except Exception as e_descarga:
        print(f"\n❌ Error al obtener/guardar la transcripción: {e_descarga}")
        return

    # 2. Intentar procesar con Gemini
    try:
        resultado = detectar_momentos_virales(transcript_marcas)

        print("\n" + "="*50)
        print("🎯 CORTES RECOMENDADOS PARA SHORTS / REELS")
        print("="*50)

        for idx, short in enumerate(resultado.shorts, 1):
            duracion = short.end_seconds - short.start_seconds
            print(f"\n🎬 SHORT #{idx}: {short.titulo}")
            print(f"⏱️ Intervalo: {short.start_time} - {short.end_time} ({short.start_seconds}s a {short.end_seconds}s) [Total: {duracion}s]")
            print(f"🪝 Hook: \"{short.gancho_primeros_3_seg}\"")
            print(f"💡 Por qué funciona: {short.por_que_es_viral}")

    except Exception as e_ia:
        print(f"\n⚠️  Aviso sobre la llamada a Gemini: {e_ia}")
        print(f"✅ El fichero '{ruta_archivo}' contiene toda la transcripción con marcas lista para usar.")

if __name__ == "__main__":
    main()