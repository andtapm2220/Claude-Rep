# Tarea diaria del agente de empleo (modo plan de Claude, sin API key)


> **REGLA DE VIGENCIA (obligatoria).** `collect` abre la página real de cada candidata y marca su vigencia como
> ABIERTA, CERRADA o SIN VERIFICAR. Las cerradas se descartan solas, y las publicadas hace más de 60 días
> también, porque son ofertas fantasma.
> - En el informe, **solo se presentan como recomendadas las ofertas ABIERTAS**, siempre con su fecha de cierre.
> - Una oferta SIN VERIFICAR nunca se presenta como recomendada; si se menciona, lleva la advertencia "verificar plazo".
> - Nunca se afirma que una oferta está abierta basándose en un resumen de búsqueda.

Instrucciones que sigue Claude Code en la sesión programada cada mañana. Todo corre dentro del plan de
Claude del usuario: la IA es la propia sesión; el código Python solo hace lo mecánico.

## Datos fijos
- Repo: `/home/user/Claude-Rep`, carpeta `job-agent/`, rama `claude/vigilant-archimedes-nvd4mi`.
- CV (Google Doc, conector Google Drive): id `1iOGErM1n7C9gjhvAAH5i1xZbUj2RKTJB5_q-aB8RcL0`.
- Planilla (conector Google Sheets): id `18mk6iS-QoWXZFO-MEaf9bgmnVXPWoYItaswq4sl03XY`, hoja `Hoja 1`.
- Perfil y preferencias: `job-agent/config/profile.yaml`.

## Pasos
1. **Preparar:** `cd /home/user/Claude-Rep && git pull --ff-only origin claude/vigilant-archimedes-nvd4mi`.
   Luego `cd job-agent && pip install -q -r requirements.txt`.
2. **Leer** el CV desde Drive y `config/profile.yaml`.
3. **Buscar en la web, como en Google.** Primero corre `python -m jobagent rotacion` y busca los empleadores del
   directorio que tocan hoy (embajadas, organismos, mineras, transnacionales), agrupando 4-5 por búsqueda (bancos y SAFI juntos con OR). Después,
   unas 4-6 búsquedas más (en español, inglés y francés) sobre estos temas:
   - consultorías de finanzas públicas, presupuesto o gestión fiscal en Bolivia (BID, Banco Mundial, CAF, FONPLATA,
     ONU, UE/EUROsociAL, GIZ, AFD, Enabel);
   - vacantes de finanzas en organismos internacionales, banca y microfinanzas en La Paz;
   - FP&A o financial analyst remoto para LatAm pagado en USD/EUR;
   - publicaciones públicas en Facebook o LinkedIn con convocatorias de finanzas en La Paz.

   Solo cuentan convocatorias concretas y **abiertas** cuya URL apareció en los resultados. Nunca inventes URLs.
   Guárdalas en `state/web_jobs.json` como una lista de objetos con estos campos: `theme`, `url`, `title`,
   `organization`, `location`, `remote`, `posted_date` (AAAA-MM-DD o vacío), `deadline` (AAAA-MM-DD o vacío),
   `description`, `contact_email`.
4. **Recolectar:** `python -m jobagent collect` (tarda 5-8 min; usa un timeout de 10 min). Genera `output/candidatas.md`.
5. **Puntuar:** lee `output/candidatas.md` y evalúa cada `id` contra el CV y el perfil, como reclutador honesto y exigente:
   - 80+ = cumple casi todo y es lo que busca; 60-79 vale la pena; 40-59 parcial; menos de 40 no encaja.
   - Licitaciones para empresas, eventos o puestos operativos van como `descartar`.
   - `red_flags` lista señales de estafa u oferta fantasma.

   Escribe `state/scores.json` como una lista de objetos con estos campos: `id`, `score`, `verdict`
   (postular_ya | vale_la_pena | parcial | descartar), `reasons` (lista), `gaps` (lista), `red_flags` (lista),
   `summary` (1-2 frases en español).
6. **Publicar:** `python -m jobagent publish`. Genera `output/ofertas_<fecha>.md` y `output/sheet_rows.json`.
7. **Planilla:** agrega las filas de `output/sheet_rows.json` a la planilla con `append_values` (rango `Hoja 1!A1`).
8. **Informe en la sesión (corto, sin extras):** solo la mejor oferta recomendada, ABIERTA, con cargo, organización,
   puntaje, fecha de cierre y enlace, más el enlace a la planilla: https://docs.google.com/spreadsheets/d/18mk6iS-QoWXZFO-MEaf9bgmnVXPWoYItaswq4sl03XY
   No escribas borradores de email, cartas, checklists ni comentarios sobre las demás.
   Si no hay recomendadas: "Sin recomendadas hoy" + enlace a la planilla.
9. **Avisar:** notificación al celular (PushNotification), una línea: la mejor oferta y su cierre. Solo si hay recomendada.
10. **Guardar memoria:** ejecuta `git add -f state/jobs.db`, luego
    `git commit -m "job-agent: estado <fecha>"` y `git push origin claude/vigilant-archimedes-nvd4mi`,
    reintentando si falla la red.
11. **Solo los lunes, pituto:** busca señales de contratación de las últimas semanas (proyectos nuevos del BID, BM, CAF,
    FONPLATA o cooperación con Bolivia). Agrega al informe una sola línea con las 3 organizaciones más prometedoras.
    Sin mensajes ni borradores.

Si una fuente falla, sigue con las demás (no hace falta mencionarlo). Si no hay recomendadas, dilo en una línea
y no envíes notificación.
