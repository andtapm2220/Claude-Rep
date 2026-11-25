# job-agent — tu buscador de empleo diario con Claude

> **Cómo funciona hoy (modo plan, sin API key).** Tres tareas programadas abren cada una **una sesión nueva** de
> Claude Code en la nube: diaria a las 06:34, nocturna liviana a las 20:34 (lunes a sábado) y profunda los domingos a
> las 23:02 (hora de Bolivia). Cada sesión sigue `TAREA_DIARIA.md`, `TAREA_NOCHE.md` o `TAREA_DOMINGO.md`.
> - **Datos:** portales, LinkedIn sin cuenta, PNUD, vigía de páginas (`config/directorio.yaml`) y búsqueda web de Claude.
> - **Proceso:** `python -m jobagent collect` (recolecta y verifica la vigencia en la página real) → Claude puntúa →
>   `python -m jobagent publish` → filas a la planilla de Google Sheets → commit de `state/jobs.db` (memoria).
> - **Salida:** la mejor oferta abierta y el enlace a la planilla. Reglas para Claude en `CLAUDE.md`.
> - **Aprendizaje:** marca en la columna P de la planilla `postulé`, `entrevista` o `no me interesa`; la corrida diaria
>   la lee antes de puntuar. `python -m jobagent fuentes` mide qué fuentes rinden (el domingo se revisa).
> - **Pendiente:** validar las viñetas `VALIDAR` del CV. Lo que sigue abajo describe el modo con API (GitHub Actions), hoy secundario.

Todos los días, a las 07:43 (hora de Bolivia), el agente:

1. **Busca** ofertas nuevas en:
   - **Portales:** Trabajito, Computrabajo Bolivia, Trabajópolis (si no bloquea), Get on Board (Latinoamérica) y Remotive (remoto).
   - **LinkedIn** sin iniciar sesión: no usa tu cuenta, así que no hay cuenta que banear. Trae sólo ofertas de las últimas 24 h, a bajo volumen y con pausas.
   - **Tus alertas por email** (Gmail): LinkedIn, Trabajando, Trabajópolis, Indeed… Creas alertas en cada portal y el agente las lee.
   - **Explorador web con Claude**, el reemplazo de "buscar en Google": organismos internacionales (ONU, BID, Banco Mundial, CAF), embajadas y cooperación (GIZ, JICA, AECID, COSUDE…), ONG, sector público y financiero (ministerios, BCB, ASFI, SICOES), publicaciones **públicas** de Facebook y LinkedIn, y una búsqueda general de tus cargos.
   - **ReliefWeb** (ONU/OCHA): ONG y cooperación en Bolivia, si configuras el appname.
   - **PNUD**: feed oficial de vacantes en Bolivia, con fecha de cierre.
   - **Vigía de páginas**: boletín Redesma/CEBEM (FAO, Helvetas, IICA, Ayuda en Acción…), UNITAS, WCS y
     cualquier página de convocatorias que agregues (MEFP, BCB, ASFI, embajadas). Lee también los PDF de los TDR.
   - **Lo que tú le mandes al bot:** pegas un enlace o el texto de una oferta (por ejemplo, un post de un grupo de Facebook) y te responde con la evaluación.
2. **Unifica duplicados**: si la misma oferta aparece en dos portales, queda una sola, y eso suma confianza.
3. **Verifica** que sea real y vigente: fecha de publicación, fecha de cierre, empresa identificable, si la web de la empresa existe, si el email es del dominio de la empresa, y patrones de estafa (pedir pagos, multinivel, "gana Bs X desde casa", sólo WhatsApp…).
4. **Prefiltra** sin IA: descarta cargos que no quieres y lugares que no te sirven, y ordena por palabras clave.
5. **Puntúa con Claude** (0-100) contra tu perfil y tu CV. Por cada oferta da por qué encaja, qué te falta y sus alertas.
6. **Redacta** una carta de presentación para las mejores.
7. **Te avisa por Telegram** con la lista detallada y botones: 🌐 Ver oferta · ✉️ Postular por email · 🙈 Descartar.
8. **Registra** todo en Google Sheets para que lleves el seguimiento.
9. Cada hora revisa tus botones. Si apretaste **✉️ Postular**, envía la postulación por email (carta + CV en PDF)
   desde tu cuenta, y te manda el **checklist según el tipo de empleador**:
   - **Estado:** CV firmado, respaldos, declaración jurada, SICOES.
   - **ONU/BID:** registro en su portal.
   - **ONG:** CV de 3 páginas, pretensión salarial y referencias.
   - **Remoto:** CV en inglés y forma de cobro.
10. **Cada lunes, "pituto inteligente":** Claude busca señales de contratación que llegan *antes* de la convocatoria
    (préstamos nuevos del BID, Banco Mundial y CAF, programas de cooperación, empresas que se expanden). Te sugiere
    5 organizaciones, a quién escribirle, un enlace de búsqueda en LinkedIn y un mensaje listo. Va por el canal por
    donde se consigue la mayoría de los empleos en la región: los contactos.

### Tu CV
- Localmente se lee de `config/cv.local.md`, que **no se sube al repo**. En GitHub, pega ese texto en el secreto `CV_TEXT`.
- Revisa las viñetas de tu rol actual en el MEFP: están marcadas con `VALIDAR`.

> **¿Por qué no postula sólo?** La investigación previa mostró que los bots de postulación masiva
> rinden igual o peor que postular poco y bien. Por ejemplo, 5.000 postulaciones automáticas dieron
> 20 entrevistas, las mismas que 300 manuales, y LinkedIn e Indeed suspenden cuentas por automatizar.
> Aquí la IA hace el 95 % del trabajo y tú das el OK con un toque. En Bolivia muchas ofertas piden
> "enviar CV a rrhh@empresa", así que postular por email es el canal más directo y no viola los
> términos de ningún portal.

## Puestos internacionales (agregado 25-11-2026)
- `config/directorio.yaml`, sección `internacional_sede_afuera`: organismos con sede fuera de Bolivia (BM, BID, CAF,
  FONPLATA, FMI, ONU/CEPAL, CAN, FLAR, CEMLA, CIAT, OEA, Cancillería...). FONPLATA y la Cancillería se vigilan a
  diario; el resto entra en la rotación, que para esta categoría busca sin la palabra "Bolivia".
- `config/convocatorias_anuales.yaml`: programas de jóvenes profesionales y pasantías que abren una vez al año; la
  corrida del domingo los revisa (paso 6c). `profile.yaml` acepta ahora puestos presenciales en esos países.
- Planilla: no se escriben las CERRADAS ni las SIN VERIFICAR de menos de 60; antes de agregar se quitan duplicados.

## Configuración (una sola vez, ~20 min)

### 1. Tu perfil
- `config/profile.yaml`: cargos objetivo, palabras clave, exclusiones, ciudades, preferencias y deal-breakers.
- Tu CV en texto: guárdalo como **secreto `CV_TEXT`**, recomendado para que no quede público en el repo, o pégalo en `config/cv.md`.

### 2. Secretos en GitHub
En *Settings → Secrets and variables → Actions → New repository secret*:

| Secreto | Para qué | Cómo obtenerlo |
|---|---|---|
| `ANTHROPIC_API_KEY` | Puntuar y redactar con Claude | console.anthropic.com → API Keys |
| `TELEGRAM_BOT_TOKEN` | Enviarte las ofertas | En Telegram, habla con **@BotFather** → `/newbot` |
| `TELEGRAM_CHAT_ID` | A quién enviarlas | Escríbele "hola" a tu bot y luego corre `python -m jobagent chatid` con el token |
| `CV_TEXT` | Tu CV (privado) | Pega el texto del CV |
| `CV_PDF_BASE64` *(opcional)* | Adjunto al postular | `base64 -w0 cv.pdf` y pega el resultado |
| `SMTP_USER`, `SMTP_PASSWORD` *(opcional)* | Enviar postulaciones por email | Gmail → Cuenta → Seguridad → Verificación en 2 pasos → **Contraseñas de aplicación** |
| `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` *(opcional)* | Registro en Sheets | Crea una cuenta de servicio en Google Cloud, descarga su JSON y comparte la planilla con su email. El ID está en la URL de la planilla. |
| `IMAP_USER`, `IMAP_PASSWORD` *(opcional)* | Leer tus alertas de empleo del Gmail | Las mismas que `SMTP_*`, o una cuenta de Gmail sólo para alertas (recomendado). Si no los pones, usa `SMTP_*`. |
| `RELIEFWEB_APPNAME` *(opcional)* | Ofertas de ONG/ONU vía ReliefWeb | Solicitud gratuita en apidoc.reliefweb.int/parameters#appname |

### Alertas por email (la forma segura de cubrir LinkedIn, Trabajando y otros)
1. En LinkedIn → Empleos → busca "economista" en Bolivia → activa **Alerta de empleo** (diaria, por email).
2. Haz lo mismo en Trabajando.com.bo, Trabajópolis, Computrabajo e Indeed.
3. Lo ideal es que esas alertas lleguen a un Gmail dedicado. El agente lo lee en modo sólo lectura.

### 3. Activarlo
GitHub sólo ejecuta los workflows programados desde la **rama principal**. Haz merge de esta rama a `main`
y luego ve a *Actions → job-agent → Run workflow* para probarlo al instante.

## Probar en tu computadora
```bash
cd job-agent
pip install -r requirements.txt
python -m jobagent run --no-llm --limit-sources 5   # sin gastar IA, imprime en consola
export ANTHROPIC_API_KEY=...; python -m jobagent run  # corrida real
python -m pytest -q tests
```

## Costo (estimado)
- GitHub Actions: gratis en repo público. En repo privado, la corrida diaria más la revisión de Telegram cada hora
  usan unos 900-1.200 min/mes, dentro de los 2.000 gratis.
- Puntaje de Claude: el perfil y el CV se guardan en caché y se evalúan unas 40 ofertas por día. Con
  `claude-opus-5-5` son centavos de dólar por día.
- **Explorador web: es la parte más cara.** Son 6 temas × hasta 5 búsquedas = ~30 búsquedas por día
  (USD 10 por cada 1.000 búsquedas), más leer los resultados. Con Opus calcula aproximadamente USD 1-3 por día.
  Para bajarlo, pon `explorador_web.model: "claude-sonnet-5-5"`, baja `max_searches_per_theme`, o deja sólo
  los temas que más te sirven.

## Qué se hace con Facebook, LinkedIn y Google (y qué no)
| Fuente | Cómo | Riesgo de baneo |
|---|---|---|
| Google | Búsqueda web de Claude (la API de búsqueda de Google cierra en enero de 2027 y ya no acepta clientes nuevos) | Ninguno |
| LinkedIn | Endpoint público de invitado + tus alertas por email | Ninguno para tu cuenta: no se usa. LinkedIn sólo puede frenar la IP un rato (HTTP 429) y el agente se detiene solo |
| Facebook | Sólo publicaciones **públicas** que aparecen en buscadores, más lo que tú le reenvíes al bot | Ninguno |
| Grupos de Facebook con login | **No se hace.** Requiere automatizar tu cuenta: viola los términos de Meta y suspenden cuentas por eso | Alto |

## Ajustar los resultados
- ¿Llegan demasiadas ofertas? Sube `agente.puntaje_minimo` o agrega palabras a `excluir_titulo`.
- ¿Llegan muy pocas? Bájalo, agrega `keywords` o agrega regiones (`santa-cruz`, `cochabamba`) en `fuentes`.
- ¿Buscas en más países? Agrega países en `fuentes.getonbrd.countries` y en `paises_region`.

## Limitaciones conocidas
- **Trabajando.com.bo y Trabajópolis** usan Cloudflare y bloquean los servidores de datacenter, incluido GitHub Actions.
  Trabajópolis se intenta cada día y se omite si bloquea. Para cubrirlos de verdad habría que correr el agente
  desde una IP residencial, por ejemplo tu propia PC con el Programador de tareas.
- LinkedIn no se usa con tu cuenta: sólo en modo invitado y mediante tus alertas por email.
- El portal "Oportunidades ONU Bolivia" estaba en mantenimiento (noviembre de 2026). El explorador web cubre
  directamente las páginas de empleo de cada agencia.
- Postular dentro de los formularios de los portales (no por email) queda como siguiente fase. Requiere
  tus credenciales del portal y que lo apruebes oferta por oferta.
