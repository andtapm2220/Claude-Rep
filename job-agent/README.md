# job-agent — tu buscador de empleo diario con Claude

Todos los días, a las 07:43 (hora de Bolivia), el agente:

1. **Busca** ofertas nuevas en Trabajito, Computrabajo Bolivia, Trabajópolis (si no bloquea), Get on Board (Latinoamérica) y Remotive (remoto).
2. **Unifica duplicados**: si la misma oferta aparece en dos portales, queda una sola, y eso suma confianza.
3. **Verifica** que sea real y vigente: fecha de publicación, fecha de cierre, empresa identificable, si la web de la empresa existe, si el email es del dominio de la empresa, y patrones de estafa (pedir pagos, multinivel, "gana Bs X desde casa", sólo WhatsApp…).
4. **Prefiltra** sin IA: descarta cargos que no quieres y lugares que no te sirven, y ordena por palabras clave.
5. **Puntúa con Claude** (0-100) contra tu perfil y tu CV. Por cada oferta da por qué encaja, qué te falta y sus alertas.
6. **Redacta** una carta de presentación para las mejores.
7. **Te avisa por Telegram** con la lista detallada y botones: 🌐 Ver oferta · ✉️ Postular por email · 🙈 Descartar.
8. **Registra** todo en Google Sheets para que lleves el seguimiento.
9. Cada 2 horas revisa tus botones. Si apretaste **✉️ Postular**, envía la postulación por email (carta + CV en PDF) desde tu cuenta.

> **¿Por qué no postula sólo?** La investigación previa mostró que los bots de postulación masiva
> rinden igual o peor que postular poco y bien. Por ejemplo, 5.000 postulaciones automáticas dieron
> 20 entrevistas, las mismas que 300 manuales, y LinkedIn e Indeed suspenden cuentas por automatizar.
> Aquí la IA hace el 95 % del trabajo y tú das el OK con un toque. En Bolivia muchas ofertas piden
> "enviar CV a rrhh@empresa", así que postular por email es el canal más directo y no viola los
> términos de ningún portal.

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

## Costo
- GitHub Actions: gratis (repo público), o ~3 min por día dentro de la cuota gratuita (repo privado).
- Claude: el perfil y el CV se guardan en caché y se evalúan unas 40 ofertas por día. Con `claude-opus-5-5`
  son unos pocos centavos de dólar por día. Para gastar aún menos, cambia `agente.modelo` a `claude-haiku-5-5`.

## Ajustar los resultados
- ¿Llegan demasiadas ofertas? Sube `agente.puntaje_minimo` o agrega palabras a `excluir_titulo`.
- ¿Llegan muy pocas? Bájalo, agrega `keywords` o agrega regiones (`santa-cruz`, `cochabamba`) en `fuentes`.
- ¿Buscas en más países? Agrega países en `fuentes.getonbrd.countries` y en `paises_region`.

## Limitaciones conocidas
- **Trabajando.com.bo y Trabajópolis** usan Cloudflare y bloquean los servidores de datacenter, incluido GitHub Actions.
  Trabajópolis se intenta cada día y se omite si bloquea. Para cubrirlos de verdad habría que correr el agente
  desde una IP residencial, por ejemplo tu propia PC con el Programador de tareas.
- LinkedIn no se incluye a propósito: lo prohíben sus términos, bloquea a los bots y arriesga tu cuenta.
- Postular dentro de los formularios de los portales (no por email) queda como siguiente fase. Requiere
  tus credenciales del portal y que lo apruebes oferta por oferta.
