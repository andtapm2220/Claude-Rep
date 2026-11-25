# job-agent: reglas para Claude

Agente diario de búsqueda de empleo para Fernando. Python hace lo mecánico: bajar, filtrar, verificar vigencia y
guardar la memoria en `state/jobs.db`. Claude busca en la web, puntúa y publica. Los pasos están en
`TAREA_DIARIA.md`, `TAREA_NOCHE.md` y `TAREA_DOMINGO.md`. El resumen del proyecto está en `README.md`.

## Reglas del proyecto (obligatorias)
- **Vigencia:** solo se recomienda una oferta marcada ABIERTA por `validate.py`, que abre la página real. Nunca se
  afirma que una oferta está abierta basándose en un resumen de búsqueda.
- **URLs:** nunca se inventan. Solo valen las que aparecieron en los resultados o están guardadas en la base.
- **Privacidad:** el CV con datos personales vive en Drive y en `config/cv.local.md`, que no se sube al repo. Nunca
  se comparten el email ni los datos de Fernando con servicios externos.
- **Salida de cada corrida:** solo la mejor oferta recomendada (cargo, organización, puntaje, cierre y enlace) más el
  enlace a la planilla, y en la corrida diaria una línea "Pituto" con contactos públicos si la mejor tiene 70 o más.
  Sin borradores de email, cartas, checklists ni sugerencias extra.
- **Planilla:** las CERRADAS no se escriben (lo hace `publish`) y antes de agregar filas se quitan las que ya están
  (misma URL o mismo código de convocatoria). Al final se ordena por Fecha y Puntaje, descendente.

## Ahorro de tokens
- No leer archivos enteros si basta una parte. No releer lo que ya está en contexto.
- No narrar ni explicar pasos rutinarios. No hacer búsquedas web en la corrida nocturna.
- Las respuestas al usuario van cortas y en español.

## Criterio de código: lo mínimo que funciona
Adaptado de ponytail (DietrichGebert/ponytail, MIT) y de andrej-karpathy-skills (multica-ai).
- Antes de escribir código nuevo, buscar si ya existe algo reutilizable en `jobagent/`.
- Preferir la librería estándar o lo ya instalado (`requirements.txt`) antes que dependencias nuevas.
- No agregar abstracciones, configuración ni andamiaje que nadie pidió.
- Cambios quirúrgicos: cada línea debe responder al pedido; respetar el estilo existente.
- En un error, corregir la causa raíz (revisar todos los llamadores), no solo el síntoma.
- Dejar una verificación mínima ejecutable: `python -m pytest -q` en `job-agent/`.
- Nunca simplificar la validación de entradas, el manejo de errores que evita perder datos ni la seguridad.
- Ante ambigüedad real, declarar los supuestos y preguntar antes de construir.

## Trazabilidad (idea tomada de Graphify, Apache-2.0)
- Al puntuar, separar lo leído en la oferta, lo inferido del CV y lo dudoso. Lo dudoso va en `gaps` o `red_flags`.
- La memoria (`state/jobs.db`) evita reevaluar lo ya visto. Se guarda con commit al final de cada corrida.

## Subagentes
Se pueden usar en paralelo si las partes son independientes: **haiku** para lo mecánico, **sonnet** para lo que
exige criterio. Ante duda, sonnet. No se usan si dos agentes tocarían el mismo archivo o si la tarea es corta.
