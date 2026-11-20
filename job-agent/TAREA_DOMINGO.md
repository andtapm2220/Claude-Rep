# Corrida profunda del domingo (23:02 Bolivia)

El límite de uso del plan de Fernando se reinicia el lunes a las 01:00. Esta corrida aprovecha lo que haya sobrado de
la semana. **Si se alcanza el límite a mitad de camino, no pasa nada**: todo lo evaluado se guarda por tandas, y lo
pendiente queda para el lunes. Por eso hay que avanzar en orden de valor y guardar seguido. Usa los mismos datos fijos
que `TAREA_DIARIA.md`.

1. **Preparar:** `cd /home/user/Claude-Rep && git pull --ff-only origin claude/vigilant-archimedes-nvd4mi && cd job-agent`.
   Después, `rm -f state/web_jobs.json state/pending.json state/scores.json`.
2. **Leer** el CV desde Drive y `config/profile.yaml`.
3. **Búsqueda amplia, en orden de prioridad:**
   - `python -m jobagent rotacion --todo` lista los 141 empleadores del directorio sin página vigilada, con los de
     prioridad alta primero. Búscalos todos, agrupando 4-5 por búsqueda.
   - Después, búsquedas libres de: finanzas públicas y gestión fiscal (BID, BM, CAF, UE, cooperación), FP&A y
     finanzas remoto en USD/EUR, banca y microfinanzas en La Paz, y consultorías por producto.
   - Cada 10 búsquedas, guarda lo encontrado en `state/web_jobs.json`, con el mismo formato que la corrida diaria.
4. `python -m jobagent collect --max 80`.
5. **Puntuar por tandas de 20**, en el orden en que aparecen en `output/candidatas.md`:
   - Escribe `state/scores.json` con esas 20.
   - Corre `python -m jobagent publish --parcial` y agrega las filas de `output/sheet_rows.json` a la planilla.
   - Haz commit y push de `state/jobs.db` (forzado con `-f`).
   - Repite con las siguientes 20 hasta terminar.
6. **Cierre:** `python -m jobagent publish` con un `state/scores.json` vacío (`[]`), para guardar como vistas
   las no candidatas. Luego, commit y push.
7. **Informe:**
   - Escribe en la conversación las recomendadas de la semana que encontraste esta noche.
   - Agrega cualquier empleador del directorio que ya no opera en Bolivia, para sacarlo.
   - Envía una notificación al celular solo si hay algo de 70 o más.
