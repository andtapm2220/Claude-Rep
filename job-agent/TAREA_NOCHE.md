# Corrida nocturna liviana (lunes a sábado, 20:34 Bolivia)

Objetivo: enterarse el mismo día de convocatorias nuevas, gastando poco del plan
(aproximadamente un 10-20 % de la corrida de la mañana). Usa los mismos datos fijos que
`TAREA_DIARIA.md` (repo, CV en Drive, planilla).

1. `cd /home/user/Claude-Rep && git pull --ff-only origin claude/vigilant-archimedes-nvd4mi && cd job-agent`.
2. **No hagas búsqueda web ni rotación.** Borra cualquier resto: `rm -f state/web_jobs.json state/pending.json state/scores.json`.
3. `python -m jobagent collect --max 10`. Solo fuentes gratuitas, con un tope de 10 candidatas.
4. Si `candidatas` es 0, salta al paso 7 y no escribas informe.
5. Lee el CV desde Drive y `output/candidatas.md`, y escribe `state/scores.json` con el mismo formato y criterio que la
   corrida de la mañana. Sé breve: `summary` de una frase, máximo 2 `reasons` y 2 `gaps`.
6. `python -m jobagent publish`. Luego agrega a la planilla las filas de `output/sheet_rows.json`.
7. Guarda la memoria: `git add -f state/jobs.db`, `git commit -m "job-agent: estado noche <fecha>"` y
   `git push origin claude/vigilant-archimedes-nvd4mi`.
8. **Solo si alguna oferta tiene 70 o más:** escribe un informe corto en la conversación (cargo, organización, puntaje,
   por qué y enlace) y envía una notificación al celular. Si no hay, termina sin escribir nada más que
   "Noche: sin novedades".
