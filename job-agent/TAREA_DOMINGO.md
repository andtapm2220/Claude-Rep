# Corrida profunda del domingo (23:02 Bolivia)


> **REGLA DE VIGENCIA (obligatoria).** `collect` abre la página real de cada candidata y marca su vigencia como
> ABIERTA, CERRADA o SIN VERIFICAR. Las cerradas se descartan solas, y las publicadas hace más de 60 días
> también, porque son ofertas fantasma.
> - En el informe, **solo se presentan como recomendadas las ofertas ABIERTAS**, siempre con su fecha de cierre.
> - Una oferta SIN VERIFICAR nunca se presenta como recomendada; si se menciona, lleva la advertencia "verificar plazo".
> - Nunca se afirma que una oferta está abierta basándose en un resumen de búsqueda.

El límite de uso del plan de Fernando se reinicia el lunes a las 01:00. Esta corrida aprovecha lo que haya sobrado de
la semana. **Si se alcanza el límite a mitad de camino, no pasa nada**: todo lo evaluado se guarda por tandas, y lo
pendiente queda para el lunes. Por eso hay que avanzar en orden de valor y guardar seguido. Usa los mismos datos fijos
que `TAREA_DIARIA.md`.

1. **Preparar:** `cd /home/user/Claude-Rep && git pull --ff-only origin claude/vigilant-archimedes-nvd4mi && cd job-agent`.
   Después, `rm -f state/web_jobs.json state/pending.json state/scores.json`.
2. **Leer** el CV desde Drive y `config/profile.yaml`.
3. **Búsqueda amplia, en orden de prioridad:**
   - `python -m jobagent rotacion --todo` lista todos los empleadores del directorio sin página vigilada, con los de
     prioridad alta primero. Búscalos todos, agrupando 4-5 por búsqueda.
   - Facebook: 4-6 búsquedas `site:facebook.com` de convocatorias de finanzas, banca y presupuesto en La Paz.
   - Internacional (sede fuera de Bolivia): 4-6 búsquedas SIN la palabra Bolivia, p. ej. "budget officer OR finance
     officer OR public finance specialist vacancy 2026 Latin America", "economista OR especialista finanzas públicas
     vacante organismo internacional Washington OR Lima OR Panamá OR Santiago". Sirven puestos en sede, regionales y
     de jóvenes profesionales.
   - Después, búsquedas libres de: finanzas públicas y gestión fiscal (BID, BM, CAF, UE, cooperación), FP&A y
     finanzas remoto en USD/EUR, banca y microfinanzas en La Paz, y consultorías por producto.
   - Cada 10 búsquedas, guarda lo encontrado en `state/web_jobs.json`, con el mismo formato que la corrida diaria.
4. `python -m jobagent collect --max 80 2>&1 | tail -2`.
5. **Puntuar por tandas de 20**, en el orden en que aparecen en `output/candidatas.md`:
   - Escribe `state/scores.json` con esas 20.
   - Corre `python -m jobagent publish --parcial` y agrega las filas de `output/sheet_rows.json` a la planilla (antes de agregar, lee la columna N (URL) de la planilla (`Hoja 1!N:N`) y quita de las filas las que ya estén (misma URL, o mismo código de convocatoria y organización, p. ej. "ON - 334 - 2026" de Banco Unión)).
   - Haz commit y push de `state/jobs.db` (forzado con `-f`).
   - Repite con las siguientes 20 hasta terminar.
6. **Cierre:** `python -m jobagent publish` con un `state/scores.json` vacío (`[]`), para guardar como vistas
   las no candidatas. Luego, commit y push.
6b. **Fuentes:** `python -m jobagent fuentes`. Si una fuente lleva 30 o más vistas y 0 recomendables, menciónala en una
   línea del informe como candidata a quitarse. No la quites sin el OK de Fernando.
6c. **Programas anuales:** lee `config/convocatorias_anuales.yaml`. Para cada uno con ajuste alta o media, haz UNA
   búsqueda web ("<programa> 2027 application deadline" o "convocatoria 2027"). Si encuentras una convocatoria abierta,
   o una que abre o cierra en los próximos 45 días, actualiza su `ventana` en el YAML (con la URL vista) y agrega al
   informe una línea "Programa: <nombre>, abre/cierra <fecha>, <url>". Si ninguna, no escribas nada.
7. **Informe (corto):** la mejor oferta recomendada de la noche (cargo, organización, puntaje, cierre y enlace), el
   enlace a la planilla (https://docs.google.com/spreadsheets/d/18mk6iS-QoWXZFO-MEaf9bgmnVXPWoYItaswq4sl03XY) y, en una línea, los empleadores del directorio que ya no operan en Bolivia.
   Envía una notificación al celular solo si hay algo de 70 o más.
