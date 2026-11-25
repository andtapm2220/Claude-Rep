# Corrida nocturna liviana (lunes a sábado, 20:34 Bolivia)


> **REGLA DE VIGENCIA (obligatoria).** `collect` abre la página real de cada candidata y marca su vigencia como
> ABIERTA, CERRADA o SIN VERIFICAR. Las cerradas se descartan solas, y las publicadas hace más de 60 días
> también, porque son ofertas fantasma.
> - En el informe, **solo se presentan como recomendadas las ofertas ABIERTAS**, siempre con su fecha de cierre.
> - Una oferta SIN VERIFICAR nunca se presenta como recomendada; si se menciona, lleva la advertencia "verificar plazo".
> - Nunca se afirma que una oferta está abierta basándose en un resumen de búsqueda.

Objetivo: enterarse el mismo día de convocatorias nuevas, gastando poco del plan
(aproximadamente un 10-20 % de la corrida de la mañana). Usa los mismos datos fijos que
`TAREA_DIARIA.md` (repo, CV en Drive, planilla).

1. `cd /home/user/Claude-Rep && git pull --ff-only origin claude/vigilant-archimedes-nvd4mi && cd job-agent`.
2. **No hagas búsqueda web ni rotación.** Borra cualquier resto: `rm -f state/web_jobs.json state/pending.json state/scores.json`.
3. `python -m jobagent collect --max 10 2>&1 | tail -2`. Solo fuentes gratuitas, con un tope de 10 candidatas.
4. Si `candidatas` es 0, salta al paso 7 y no escribas informe.
5. Lee `output/candidatas.md` y el `resumen` de `config/profile.yaml` (no hace falta abrir el CV en Drive para 10 ofertas), y escribe `state/scores.json` con el mismo formato y criterio que la
   corrida de la mañana. Sé breve: `summary` de una frase, máximo 2 `reasons` y 2 `gaps`.
6. `python -m jobagent publish`. Luego, antes de agregar, lee la columna N (URL) de la planilla (`Hoja 1!N:N`) y quita de las filas las que ya estén (misma URL, o mismo código de convocatoria y organización, p. ej. "ON - 334 - 2026" de Banco Unión), y agrega a la planilla las filas de `output/sheet_rows.json`.
7. Guarda la memoria: `git add -f state/jobs.db`, `git commit -m "job-agent: estado noche <fecha>"` y
   `git push origin claude/vigilant-archimedes-nvd4mi`.
8. **Solo si alguna oferta tiene 70 o más:** escribe una línea con la mejor (cargo, organización, puntaje, cierre y
   enlace) más el enlace a la planilla (https://docs.google.com/spreadsheets/d/18mk6iS-QoWXZFO-MEaf9bgmnVXPWoYItaswq4sl03XY), y envía una notificación al celular. Si no hay, termina con
   "Noche: sin novedades".
