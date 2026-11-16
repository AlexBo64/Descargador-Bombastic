---
name: nueva-fase
description: Construye la siguiente fase (o la fase indicada) del plan de Descargador Bombastic siguiendo el ritual del proyecto. Úsala cuando el usuario pida empezar, continuar o construir una fase.
---

# Construir una fase

Argumento opcional: el número de fase. Si no se da, es la primera marcada como "Pendiente" en la
hoja de ruta del `README.md`.

## Antes de escribir código

1. Lee `docs/ESPECIFICACION.md` (la sección 9 define el alcance de cada fase y la 10 los tests
   mínimos), `docs/ARQUITECTURA.md` y `CHANGELOG.md`.
2. Comprueba que el punto de partida está sano: `ruff check .`, `mypy` y `python -m pytest`.
   Si algo falla, arréglalo o avisa antes de continuar.
3. Presenta al usuario:
   - la lista de archivos que vas a crear o modificar;
   - cualquier decisión de la especificación que te parezca mala, con la alternativa y el motivo;
   - cualquier cosa que no se pueda hacer bien y la mejor alternativa razonable.
   Si hay una decisión que cambie el diseño, espera su respuesta. Si no, continúa.

## Durante la fase

- Cíñete al alcance de la fase. No adelantes funciones de fases posteriores.
- Lógica primero en `bombastic/core/` con sus tests; después la interfaz.
- Cada texto nuevo va a `es.json` y `en.json`.
- Para probar procesos externos usa scripts falsos que imiten la salida de yt-dlp y ffmpeg,
  no los binarios reales. Los tests con red llevan la marca `integration`.
- Prioriza que funcione y sea robusto sobre añadir funciones.

## Al terminar

1. Ejecuta `ruff format .`, `ruff check .`, `mypy` y `python -m pytest`. Todo debe pasar.
2. Arranca la app (`python -m bombastic`) y comprueba a mano lo nuevo, si el entorno lo permite.
3. Actualiza `README.md` (hoja de ruta, instrucciones, preguntas frecuentes que ya apliquen),
   `CHANGELOG.md`, `docs/ARQUITECTURA.md` si cambió algo, y `THIRD_PARTY_LICENSES.txt` si hay
   dependencias nuevas.
4. Sube la versión menor en `bombastic/__init__.py` y `pyproject.toml` (una por fase: 0.2.0 para
   la Fase 1, 0.3.0 para la Fase 2…).
5. Propón un commit con el mensaje `Fase N: <resumen>`. No hagas push sin que te lo pidan.
6. Para y entrega un resumen con: qué se ha hecho, qué falta o difiere de la especificación, y
   cómo probarlo paso a paso. No empieces la fase siguiente sin confirmación.
