import os
import sys
import re
import json
import urllib.request
from google import genai
from google.genai import types
from youtube_transcript_api import YouTubeTranscriptApi

def extraer_video_id(url_o_id: str) -> str:
    """Extrae el video_id tanto si pegas la URL completa como el ID suelto."""
    patron = r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})"
    coincidencia = re.search(patron, url_o_id)
    return coincidencia.group(1) if coincidencia else url_o_id

def sanitizar_nombre_fichero(nombre: str) -> str:
    """Limpia caracteres no válidos para nombres de archivo en Windows/Linux."""
    return re.sub(r'[\\/*?:"<>|]', "", nombre).strip().replace(" ", "_")

def obtener_titulo_video(video_id: str) -> str:
    """Obtiene el título del vídeo vía oEmbed sin necesidad de Google API Key."""
    try:
        url = f"https://noembed.com/embed?url=https://www.youtube.com/watch?v={video_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            titulo = data.get("title")
            if titulo:
                return sanitizar_nombre_fichero(titulo)
    except Exception:
        pass
    return video_id

def obtener_transcripcion(video_id: str) -> str:
    print(f"📥 Descargando subtítulos automáticos para {video_id}...")
    try:
        # Compatibilidad con versión moderna (v1.x+: instancia + fetch)
        if hasattr(YouTubeTranscriptApi, 'fetch') or hasattr(YouTubeTranscriptApi(), 'fetch'):
            yt_api = YouTubeTranscriptApi()
            transcript = yt_api.fetch(video_id, languages=['es', 'es-ES'])
            # Soporta tanto lista de objetos (snippet.text) como lista de dicts (bloque['text'])
            textos = []
            for bloque in transcript:
                textos.append(getattr(bloque, 'text', None) or bloque.get('text', ''))
            return " ".join(textos)
        
        # Compatibilidad con versión clásica (<1.0: método estático get_transcript)
        elif hasattr(YouTubeTranscriptApi, 'get_transcript'):
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'es-ES'])
            return " ".join([bloque['text'] for bloque in transcript])
        
        else:
            raise RuntimeError("No se encontró ningún método válido (fetch/get_transcript) en YouTubeTranscriptApi.")
            
    except Exception as e:
        raise RuntimeError(f"Error al obtener subtítulos de YouTube: {e}")

def guardar_transcripcion(nombre_base: str, texto: str) -> str:
    ruta_archivo = f"transcripcion_{nombre_base}.txt"
    with open(ruta_archivo, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"💾 Transcripción intermedia guardada con éxito en: {ruta_archivo}")
    return ruta_archivo

def cargar_transcripcion(ruta_archivo: str) -> str:
    with open(ruta_archivo, "r", encoding="utf-8") as f:
        return f.read()

def redactar_posts(transcripcion: str, video_url: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "Falta la variable de entorno GEMINI_API_KEY. "
            "Configúrala antes de ejecutar la llamada a la IA (set GEMINI_API_KEY=tu_clave en Windows)."
        )

    client = genai.Client()
    print("🧠 Procesando y redactando los 3 posts con Gemini...")
    
    prompt = f"""
    Actúa como un estratega de contenido B2B y personal branding técnico en LinkedIn.
    A partir de la siguiente transcripción automática de un vídeo, genera exactamente 3 propuestas de publicación distintas y listas para publicar.
    
    Ángulos obligatorios:
    1. **Post 1: Insights & Claves prácticas** (3 a 5 aprendizajes rápidos, directos y aplicables, formato bullet points).
    2. **Post 2: Reflexión / Caso real / Opinión técnica** (narrativa que plantee un dilema o lección aprendida y abra debate con la comunidad).
    3. **Post 3: Resumen ejecutivo con gancho** (foco en el problema que resuelve el vídeo e invitación directa a verlo).

    Reglas de estilo:
    - Español natural y profesional, párrafos muy cortos (máximo 2-3 líneas).
    - Evita adornos vacíos o lenguaje excesivamente corporativo.
    - Incluye los saltos de línea listos para LinkedIn.
    - Cierra cada post con 3 hashtags específicos y el enlace al vídeo: {video_url}

    Transcripción del vídeo:
    {transcripcion}
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    return response.text

def main():
    # Si se pasa como argumento por línea de comandos (sys.argv[1]), lo toma directamente
    if len(sys.argv) > 1:
        entrada = sys.argv[1].strip()
    else:
        entrada = input("Pega la URL del vídeo de YouTube o su ID: ").strip()

    if not entrada:
        print("Entrada vacía. Abortando.")
        return

    video_id = extraer_video_id(entrada)
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    nombre_base = obtener_titulo_video(video_id)
    
    # -------------------------------------------------------------
    # PASO 1: Descargar transcripción y persistir fichero en disco
    # -------------------------------------------------------------
    try:
        texto_descargado = obtener_transcripcion(video_id)
        ruta_transcripcion = guardar_transcripcion(nombre_base, texto_descargado)
    except Exception as error_descarga:
        print(f"\n❌ Error en la fase de descarga/guardado: {error_descarga}")
        return

    # -------------------------------------------------------------
    # PASO 2: Cargar el fichero y procesar con Gemini
    # -------------------------------------------------------------
    try:
        texto_para_llm = cargar_transcripcion(ruta_transcripcion)
        resultado = redactar_posts(texto_para_llm, video_url)
        
        archivo_salida = f"posts_linkedin_{nombre_base}.md"
        with open(archivo_salida, "w", encoding="utf-8") as f:
            f.write(f"# Propuestas LinkedIn - Vídeo: {video_url}\n\n")
            f.write(resultado)
            
        print(f"\n✅ ¡Proceso completado! Posts guardados en: {archivo_salida}")
    except Exception as error_ia:
        print(f"\n⚠️  Fallo en la llamada a Gemini: {error_ia}")
        print(f"ℹ️  Nota: El fichero con la transcripción sigue disponible intacto en '{ruta_transcripcion}'.")

if __name__ == "__main__":
    main()