# Alerta de Citas · Lunas Oscurecidas (PNP)

Vigila el sistema de citas de la PNP cada 5 minutos y avisa por notificación push cuando se libera un cupo. Los usuarios solo se suscriben — **nadie entrega su DNI ni su clave**.

## Por qué está partido en dos servicios

Vercel no puede hacer la vigilancia: sus funciones son serverless (se ejecutan y mueren, no mantienen un proceso vivo) y su cron gratuito corre **una vez al día**. GitHub Actions sí permite cron cada 5 minutos, gratis e ilimitado en repositorios públicos, y ejecuta Chromium sin problema.

Así que: **GitHub Actions vigila, Vercel muestra.**

## Piezas

| Archivo | Qué hace |
|---|---|
| `checker.py` | Consulta el sitio con una cuenta, escribe `web/estado.json`, difunde por ntfy |
| `.github/workflows/citas.yml` | Cron cada 5 min |
| `web/index.html` | Página pública con el estado y el botón de suscripción |
| `vercel.json` | Configuración del despliegue |
| `alerta_citas_app.py` | App de escritorio, por si prefieres correrlo local |

---

## Despliegue automático (recomendado)

Desde la carpeta del proyecto:

```bash
chmod +x deploy.sh
./deploy.sh
```

El script comprueba que tengas `git` y `gh`, inicia sesión en GitHub si hace falta, te pide los datos, crea el repositorio, carga los secrets cifrados, sube todo, personaliza la página con tu usuario y lanza la primera revisión. Al terminar te deja solo dos pasos: conectar Vercel y suscribirte en el móvil.

Necesitas [GitHub CLI](https://cli.github.com). En Windows, ejecútalo desde Git Bash o WSL.

Si prefieres hacerlo a mano, o el script falla en algún punto, sigue los pasos de abajo.

---

## Despliegue manual

### 1. Sube el proyecto a GitHub

Crea un repositorio **público** llamado `citas-pnp` (público para que Actions sea ilimitado) y sube estos archivos.

### 2. Elige tu tema de ntfy

Un nombre difícil de adivinar, por ejemplo `citas-pnp-a7f3c9e2b1`. Anótalo: lo usarás en dos sitios.

### 3. Configura los secrets

En el repo: **Settings → Secrets and variables → Actions**.

En la pestaña *Secrets*, botón *New repository secret*:

| Nombre | Valor |
|---|---|
| `PNP_DNI` | tu documento |
| `PNP_CLAVE` | tu clave |
| `NTFY_TOPIC` | el tema del paso 2 |

En la pestaña *Variables* (opcionales):

| Nombre | Valor |
|---|---|
| `SEDE` | `1` para Lima-La Victoria |
| `FECHA_OBJETIVO` | `2026-11-20` — avisa solo de cupos anteriores. Vacío = cualquiera |
| `PNP_TIPO_DOC` | `1` DNI · `2` carnet de extranjería |

### 4. Activa el workflow

Pestaña **Actions** → habilita los workflows → abre *Monitor de citas PNP* → **Run workflow**. Debería terminar en verde y dejar un commit nuevo en `web/estado.json`.

### 5. Publica la página en Vercel

Antes de desplegar, edita las tres líneas del final de `web/index.html`:

```js
const USUARIO_REPO = "tu-usuario";
const NOMBRE_REPO  = "citas-pnp";
const TEMA_NTFY    = "citas-pnp-a7f3c9e2b1";
```

Luego en vercel.com: **Add New → Project**, importa el repositorio, y despliega. La configuración ya viene en `vercel.json`, no toques nada.

Listo. Comparte la URL: quien entre ve el estado en vivo y se suscribe en dos toques.

---

## Cómo llegan las alertas

La página lee `estado.json` directamente desde GitHub, así que se actualiza sin necesidad de redesplegar Vercel. En paralelo, cuando aparece un cupo nuevo el checker publica en ntfy y todos los suscriptores reciben el push a la vez.

El aviso solo se dispara cuando el conjunto de fechas **cambia**, no en cada revisión. Así nadie recibe el mismo mensaje veinte veces.

---

## Lo que conviene tener claro

**El cron de GitHub se retrasa.** `*/5 * * * *` es la intención, no una garantía: en horas de mucha carga la cola puede irse a 10 o 15 minutos. Para el caso de uso es aceptable, pero no prometas "aviso en 5 minutos exactos". Si necesitas precisión real, la alternativa es una VM pequeña (Oracle Cloud tiene un nivel gratuito permanente) corriendo `alerta_citas_app.py --consola`.

**Tu cuenta es la que consulta.** Todas las revisiones salen de tus credenciales. Si el sistema detecta actividad inusual, la cuenta afectada es la tuya, no la de los usuarios. Por eso el intervalo no baja de 5 minutos.

**Nunca pidas credenciales ajenas.** El diseño evita esto a propósito. Si en algún momento te tienta añadir un formulario donde cada usuario ponga su DNI y clave para "reservar automáticamente", ten presente que pasarías a custodiar credenciales de un sistema policial de terceros, con la exposición legal que eso implica bajo la Ley 29733 de protección de datos personales. La arquitectura actual no tiene ese problema porque no hay nada que custodiar.

**El captcha es real.** Está en el HTML dentro de `<div id="MainContent_idUcitas_divcontiene2" style="display:none;">` y el sitio lo muestra justo cuando hay cupo. Por eso el sistema avisa pero no reserva.

**Si rediseñan el sitio**, todos los selectores están agrupados al inicio de `checker.py`, en un solo bloque. Ajustarlos es cuestión de minutos.
