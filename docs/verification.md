# Verificación inicial — 2026-10-08

Primera versión instalada y ejecutada en macOS arm64, Python 3.12.14.
Dependencias directas: yt-dlp 2026.8.19, openai-whisper 20250625 e
imageio-ffmpeg 0.6.0. Se usó el modelo multilingüe `small` en CPU.

## Pruebas reales

| Entrada | Resultado observado |
| --- | --- |
| Audio local en español, generado con la voz de macOS `Eddy (Spanish (Mexico))` | Transcripción de 5,518 segundos que coincide con la frase esperada; dos segmentos. |
| [Audio JFK del repositorio oficial de Whisper](https://raw.githubusercontent.com/openai/whisper/main/tests/jfk.flac) | Descarga con yt-dlp y transcripción en inglés; 11 segundos; procedencia conservada. |
| [Reel público de NASA Johnson](https://www.instagram.com/reel/Dcea3BiPTBm/) | Descarga y transcripción sin cookies ni login; 41,078 segundos y 15 segmentos; enlace, título, autor y descripción conservados. |
| Archivo de salida ya existente | Código `2`, error `output_exists`; contenido conservado byte por byte. |
| Audio corrupto y WAV silencioso | FFmpeg real; códigos `invalid_media` y `no_audio`; ningún resultado o temporal de salida abandonado. |

Frase del audio sintético en español:

> Hoy tengo tres pedidos pendientes. Voy a revisar el inventario antes de confirmar las ventas.

Para los tres casos exitosos, stdout se pudo parsear como un único JSON y se comprobó
la presencia de texto, idioma, modelo y segmentos con timestamps válidos. El JSON
guardado del caso local coincide con stdout. No se hicieron llamadas a una API de IA.

El caso español tardó 38,3 segundos incluyendo la preparación inicial; la URL JFK
tardó 8,37 segundos y el reel 7,15. Son observaciones de muestras cortas en esta
máquina, no un benchmark ni una garantía de velocidad o precisión general.

Evidencia local de esta ejecución: `/private/tmp/tools-proof-ubj1wo1b/`.
Incluye stdout JSON y stderr separado para cada caso. Esa carpeta es temporal;
este documento conserva los resultados aunque el sistema la elimine.

## Regresiones y comprobaciones

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
sh -n bin/tools
```

**14 pruebas pasan**: entrada local, procedencia de URLs, salida y diagnósticos,
fallos de descarga/inferencia, falta de voz, enlaces largos, limpieza y preservación
de archivos, incluso si el destino aparece durante la transcripción. Dos de ellas
utilizan el decoder FFmpeg real; las otras aíslan red e inferencia para hacer
repetible la prueba del contrato. `pip check` y la sintaxis del launcher también pasan.

Se escribió la prueba del contrato antes del CLI. La regresión del enlace largo
reprodujo `OSError: File name too long` antes de corregir la identificación de URLs.

## Alcance de esta evidencia

Se verificó un reel público sin sesión. No se verificaron cuentas privadas, cookies,
otros proveedores, otros modelos, aceleración GPU ni precisión en audio con música
o ruido. La extracción de ideas y redacción las realiza el agente consumidor con
las instrucciones de Allan; no son funciones de inferencia adicionales del CLI.

Whisper `small` ya quedó descargado en la caché local. El entorno `.venv` se creó
con el Python 3.12 incluido en el runtime local de Codex, sin instalar otro Python
global. Para recrearlo en otra máquina, sigue la instalación del README.

## Ampliación visual: `inspect` — 2026-10-08

Se añadió `inspect` y se conservó `transcribe` como comando de transcripción solamente.
No se añadieron dependencias: FFmpeg prepara la referencia visual y el agente
consumidor interpreta las imágenes y secuencias. La skill local `media-to-content`
incluye la selección del comando, lectura de timestamps, revisión de movimiento,
distinción entre observaciones e interpretación y guardado en el destino elegido.

### Ejecuciones reales

- `inspect` descargó de nuevo el [reel público de NASA Johnson](https://www.instagram.com/reel/Dcea3BiPTBm/)
  sin cookies ni login. El resultado conserva procedencia, video de 1080 × 1920 y
  41,08 segundos, 15 segmentos de voz, 27 fotogramas y 10 secuencias con clips y
  tiras de cuatro imágenes. Tardó 15,7 segundos en esta máquina; el paquete ocupa
  aproximadamente 13,8 MB. No es un benchmark general.
- FFmpeg marcó candidatos a cambios de escena en 8,467; 20,067; 26,667; 30,7 y
  35,1 segundos. El contrato los identifica como candidatos, sin afirmar que todos
  sean cortes ni clasificarlos automáticamente.
- Se abrió la hoja de contacto y una tira de secuencia: muestran imágenes útiles
  y ordenadas del video, incluidos subtítulos y una transición visual. Los diez
  clips se decodificaron íntegramente con FFmpeg sin errores.
- stdout se parseó como un único JSON y coincide con `inspection.json`. Todas
  las rutas del manifiesto existen, tienen contenido y apuntan al destino final.
- `transcribe` volvió a ejecutar Whisper `small` sobre el audio español local:
  reconoció exactamente la frase esperada de 5,518 segundos en 2,21 segundos,
  sin campos visuales ni llamadas a una API de IA.

Evidencia temporal: `/private/tmp/tools-inspect-proof-vnsh3iru/`. Contiene los recursos
de `nasa/`, `stdout.json`, `stderr.log`, `summary.json` y stdout/stderr del caso español.
Este registro conserva los resultados aunque el sistema elimine esa carpeta.

### Regresiones de ambos comandos

**23 pruebas pasan**, incluyendo nueve nuevas de inspección. Se escribieron primero
las regresiones principales y se observaron fallar porque el comando aún no existía.
Las pruebas visuales usan videos sintéticos reales con FFmpeg y aíslan solamente
red/inferencia: verifican el cambio rojo/azul en dos segundos, los colores de las
imágenes asociadas a sus timestamps, clips, tiras y procedencia conservada.

También cubren video sin pista de audio, falta de palabras, rechazo de audio sin
video, errores de inferencia sin publicar recursos parciales, protección del destino
existente o creado mientras se procesa y rollback de un guardado fallido que conserva
un borrador insertado por otro agente. `transcribe` conserva sus regresiones originales.

`pip check`, la sintaxis del launcher y la ayuda de ambos comandos pasan. La skill
pasó `quick_validate.py` y su enlace relativo al README se resolvió correctamente;
PyYAML se utilizó únicamente en un entorno temporal de validación, no como dependencia
del producto. No se instalaron modelos visuales ni se hicieron commits o publicaciones.

El muestreo está limitado a 48 fotogramas y 12 secuencias de hasta cuatro segundos.
Puede omitir acciones breves; se conserva el video completo para revisarlas. Esta
prueba no mide precisión de análisis semántico, movimiento de cámara o reconocimiento
de productos: esas interpretaciones corresponden al agente que abre la evidencia.

## Preparación para compartir el código — 2026-10-08

Se prepararon la licencia MIT del código original, los avisos de terceros y la
documentación de instalación sin rutas personales. Esta preparación se realizó
antes de publicar el repositorio y de recibir autorización para el commit y push.

- Las 23 regresiones, `pip check` y la sintaxis del launcher pasan.
- Se copió el código a un directorio temporal con otro nombre, excluyendo `.venv`,
  cachés y metadatos generados. Desde esa copia se construyó el wheel
  `allan_agent_tools-0.1.0-py3-none-any.whl` sin incluir dependencias.
- El wheel contiene `LICENSE` y `THIRD_PARTY_NOTICES.md`, además de los metadatos
  del autor y licencia. No contiene videos ni modelos.
- Se instaló ese wheel sin dependencias de inferencia en un entorno temporal nuevo.
  Tanto el launcher, ejecutado desde otro directorio, como el entrypoint del módulo
  funcionaron para ayuda y versión. Esta comprobación prueba empaquetado y rutas;
  no es una nueva prueba completa de descarga/transcripción en un entorno limpio.
- La skill pasó su validador desde la copia; el enlace relativo al README funciona
  y las instrucciones públicas de README/skill/AGENTS no contienen rutas personales.

No se creó un repositorio remoto, commit ni push durante esta preparación. Las
compatibilidades adicionales a macOS arm64/Python 3.12 siguen sin verificarse.
