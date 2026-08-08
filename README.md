# Alerta de citas PNP · Lunas oscurecidas

Conseguir cita para lunas oscurecidas es difícil porque los cupos aparecen sin
aviso y se agotan en minutos. Este programa revisa la página de la Policía
Nacional del Perú **cada cinco minutos, día y noche**, y te manda una
notificación al celular en cuanto aparece un cupo.

Así se ve el aviso que recibirás:

> 🚨 **CUPO DE CITA DISPONIBLE**
> 15/09/2026 — Horas: 08:00, 08:30, 09:00 — Cupos: 3
> Entra YA y reserva.

**La cita la reservas tú.** El programa solo vigila y avisa: la página de la PNP
pide un captcha para reservar, así que nadie puede hacerlo automáticamente.

Todo funciona dentro de tu computadora. Tu documento y tu clave no salen de ahí,
no se suben a internet y nadie más los ve.

---

## Lo que necesitas

- Una computadora con **Windows 10/11** o una **Mac**, con internet.
- Tu **documento y clave** del sistema de citas de la PNP (los mismos que usas
  para entrar a la página).
- Tu **celular** Android o iPhone.
- Unos **20 minutos** para dejarlo todo instalado. Es solo la primera vez.

> [!IMPORTANT]
> La computadora tiene que quedarse **encendida y sin suspenderse** para seguir
> vigilando. Si la apagas o se duerme, el programa deja de revisar y no te
> avisará. Si usas laptop, déjala enchufada a la corriente.

No necesitas saber programar. Vas a copiar y pegar cuatro instrucciones.

---

## Paso 1 · Descargar el programa

1. En esta misma página de GitHub, busca el botón verde **Code**.
2. Pulsa **Download ZIP**.
3. Busca el archivo descargado y descomprímelo:
   - **Windows:** clic derecho → *Extraer todo* → *Extraer*.
   - **Mac:** doble clic sobre el ZIP.
4. Te quedará una carpeta llamada `citas-pnp-main`. **Muévela a Documentos**
   para tenerla a mano.

Deja esa carpeta abierta, la vas a necesitar en el paso 3.

---

## Paso 2 · Instalar Docker Desktop

Docker es un programa gratuito que se encarga de todo lo técnico por dentro
(instala el navegador y las herramientas que hacen la revisión). Tú no vas a
tocarlo: solo tiene que estar instalado y abierto.

1. Descárgalo desde [docker.com](https://www.docker.com/products/docker-desktop/)
   eligiendo tu sistema (Windows o Mac).
2. Instálalo aceptando todas las opciones que vienen por defecto.
3. **Windows:** si te pide reiniciar la computadora, hazlo. Es normal.
4. Ábrelo y espera. La primera vez tarda un par de minutos.

Sabrás que está listo cuando **el ícono de la ballena 🐳 aparezca fijo** y la
ventana de Docker no muestre avisos rojos.

### Para que se recupere solo si se reinicia la PC

Dentro de Docker Desktop, entra a **Settings** (el engranaje ⚙️) → **General** y
marca la casilla:

- **Windows:** *Start Docker Desktop when you sign in*
- **Mac:** *Start Docker Desktop when you log in*

Así, si se corta la luz o reinicias, el monitor vuelve a arrancar solo.

---

## Paso 3 · Crear tu archivo de configuración

Aquí le dices al programa quién eres y a dónde mandarte los avisos.

### 3.1 · Copia el archivo de ejemplo

Dentro de la carpeta `citas-pnp-main` verás un archivo llamado
`.env.local.example`. Haz una **copia** de ese archivo en la misma carpeta
(clic derecho → Copiar, clic derecho → Pegar) y **renombra la copia** a:

```
.env.local
```

Sí, empieza con un punto y no tiene nada después de `local`. Es correcto.

> [!WARNING]
> **Windows esconde las terminaciones de los archivos**, y eso hace que este
> paso falle muy seguido. Antes de renombrar, en el Explorador ve a la pestaña
> **Vista** y marca **Extensiones de nombre de archivo**. Si al terminar el
> archivo se llama `.env.local.txt`, el programa no lo encontrará: quítale el
> `.txt` del final.

### 3.2 · Inventa tu canal privado de avisos

Tu canal es un nombre secreto. Las notificaciones viajan por ahí, así que
**cualquiera que adivine ese nombre puede ver tus avisos** o mandarte
notificaciones falsas.

No uses tu nombre ni algo fácil como `citas-pnp`. Escribe `citas-` seguido de
unas 12 letras y números tecleados al azar, sin pensarlos. Por ejemplo:

```
citas-k4m9x2vqp7rt
```

Anótalo en un papel: lo vas a escribir dos veces, en el archivo y en el celular.

### 3.3 · Rellena el archivo

Abre `.env.local` con el **Bloc de notas** (Windows) o **TextEdit** (Mac):
clic derecho sobre el archivo → *Abrir con*.

Completa solo las líneas marcadas y **no borres ni muevas nada más**:

```dotenv
PNP_DNI=12345678              ← tu número de documento
PNP_CLAVE=tuclavesecreta      ← tu clave de la página PNP
PNP_TIPO_DOC=1                ← 1 si usas DNI, 2 si usas carnet de extranjería
SEDE=1                        ← 1 es Lima–La Victoria; cámbialo solo si la PNP te indica otro
FECHA_OBJETIVO=               ← déjalo vacío (ver abajo)
NTFY_TOPIC=citas-k4m9x2vqp7rt ← el nombre secreto que inventaste
INTERVALO_MIN=5               ← revisar cada 5 minutos
```

Escribe los valores **pegados al signo `=`**, sin espacios ni comillas.
Las flechas y los textos de la derecha son explicaciones: no los copies.

Sobre `FECHA_OBJETIVO`: déjalo vacío para que te avise de **cualquier** cita.
Solo si ya tienes una cita agendada y buscas una más cercana, escribe la fecha
de la que ya tienes, en formato `2026-09-15`. Así te avisará únicamente de
citas anteriores a esa.

Guarda el archivo y ciérralo.

> [!CAUTION]
> Este archivo contiene tu clave de la PNP. **No se lo mandes a nadie** ni lo
> subas a ningún sitio. Se queda solo en tu computadora.

---

## Paso 4 · Preparar el celular

1. Instala la app **ntfy** desde App Store o Google Play. Es gratuita.
   El ícono es una campanita verde.
2. Ábrela y pulsa el botón **+**.
3. Escribe **exactamente** el mismo nombre secreto que pusiste en `NTFY_TOPIC`.
   Revisa letra por letra: si hay una sola diferencia, no llegará ningún aviso.
4. Pulsa **Subscribe** y **acepta** cuando el celular pida permiso para enviarte
   notificaciones.

> [!TIP]
> Entra a los ajustes de notificaciones del celular y permite que ntfy suene
> aunque el teléfono esté en silencio o en modo "no molestar". Un cupo dura
> pocos minutos y de noche te lo puedes perder.

---

## Paso 5 · Encender el monitor

Ahora sí hay que usar la terminal. Es solo copiar y pegar una línea.

### 5.1 · Abre la terminal dentro de la carpeta

- **Windows 11:** abre la carpeta `citas-pnp-main`, haz clic derecho sobre un
  espacio vacío y elige **Abrir en Terminal** (o *Open in Terminal*).
- **Windows 10:** abre la carpeta, mantén pulsada la tecla **Shift**, haz clic
  derecho en un espacio vacío y elige **Abrir la ventana de PowerShell aquí**.
- **Mac:** abre **Terminal** (búscala con la lupa 🔍 arriba a la derecha).
  Escribe `cd ` — la palabra *cd*, un espacio — y luego **arrastra la carpeta**
  desde el Finder hasta la ventana negra. Pulsa Enter.

**Comprueba que estás en el sitio correcto.** Escribe esto y pulsa Enter:

```bash
ls
```

(En Windows escribe `dir` en lugar de `ls`.)

Tienes que ver una lista que incluya `Dockerfile` y `checker.py`. Si no
aparecen, estás en otra carpeta: repite el paso.

### 5.2 · Enciéndelo

Copia esta línea, pégala en la terminal y pulsa Enter:

```bash
docker compose up -d --build
```

> En Windows, para pegar en la terminal se usa **clic derecho**, no Ctrl+V.

**La primera vez tarda entre 5 y 15 minutos** y verás muchísimo texto pasando.
Es normal: está descargando el navegador que hará las revisiones. No cierres la
ventana. Solo pasa la primera vez; las siguientes son cuestión de segundos.

Cuando termine y te devuelva el cursor, ya está funcionando.

---

## Paso 6 · Comprobar que todo quedó bien

Pega esto en la terminal:

```bash
docker compose logs --tail=20 monitor-citas
```

Deberías ver algo parecido a:

```text
[16:57:51] Sesion iniciada.
[16:59:31] Fechas con cupo: 0  |  Sin Cupos
[16:59:31] Sin cupos por ahora.
[16:59:31] Latido diario difundido por ntfy.
```

Eso significa que **todo funciona**: entró a la página, revisó y por ahora no
hay cupos. Que diga "Sin cupos" es lo esperado la mayoría del tiempo.

**Y lo más importante:** en tu celular debe haber llegado una notificación
silenciosa que dice **"Monitor activo"**. Si llegó, el circuito completo
funciona y ya puedes olvidarte. Si no llegó, revisa el paso 4: casi siempre es
que el nombre secreto está escrito distinto en el archivo y en la app.

Ya puedes **cerrar la ventana de la terminal**. El monitor sigue trabajando por
su cuenta.

---

## Qué avisos vas a recibir

| Aviso | Qué significa |
|---|---|
| 🚨 **CUPO DE CITA DISPONIBLE** | ¡Hay cita! Entra a la página de la PNP ya mismo. Suena fuerte. |
| ⚠️ **MONITOR AVERIADO** | El programa lleva tres intentos sin poder revisar. Lo más común es que tu clave de la PNP haya caducado. |
| 💓 **Monitor activo** | Llega una vez al día, en silencio. Es su forma de decirte "sigo vigilando". |

Si no hay cupos, **no recibirás nada**. Es normal pasar días sin notificaciones.

Tampoco te repetirá el mismo aviso una y otra vez: solo vuelve a avisar si
cambia la fecha, el horario o la cantidad de cupos.

### Cuando llegue un aviso de cupo

1. Toca la notificación: se abre la página de la PNP.
2. Entra con tu documento y clave.
3. Reserva la cita y **resuelve el captcha** (esa parte es manual).

Ten en cuenta que los cupos vuelan. Que llegue el aviso no garantiza que el
cupo siga libre cuando entres, sobre todo si tardas en verlo. No es un fallo del
programa: simplemente alguien llegó antes.

---

## El día a día

No tienes que hacer nada: el monitor trabaja solo y vuelve a arrancar si
reinicias la computadora. Estas instrucciones son por si las necesitas.

Ábrelas siempre desde la terminal en la carpeta `citas-pnp-main` (paso 5.1).

```bash
# ¿Sigue funcionando?
docker compose ps

# Ver qué ha estado haciendo
docker compose logs --tail=50 monitor-citas

# Pausarlo (por ejemplo, si te vas de viaje)
docker compose stop

# Reanudarlo
docker compose start

# Revisar AHORA MISMO, sin esperar los 5 minutos
docker compose run --rm monitor-citas bash ./run_local.sh --once
```

Si cambiaste tu clave de la PNP, edita `.env.local` con la clave nueva y luego
ejecuta `docker compose up -d --build` para que la tome.

---

## Si algo no funciona

| Lo que ves | Qué pasa y cómo se arregla |
|---|---|
| `docker: command not found` o `no se reconoce docker` | Docker Desktop no está instalado o no está abierto. Ábrelo, espera a que la ballena 🐳 quede fija y vuelve a intentar. |
| `Cannot connect to the Docker daemon` | Docker está instalado pero apagado. Ábrelo y espera un minuto. |
| `env file ... .env.local not found` | El archivo no existe o se llama `.env.local.txt`. Vuelve al paso 3.1 y muestra las extensiones en el Explorador. |
| `Falta NTFY_TOPIC en .env.local` | Esa línea quedó vacía. Ábrelo y escribe tu nombre secreto pegado al `=`. |
| `Todavia no completaste .env.local` | Dejaste los textos de ejemplo `TU_DOCUMENTO` o `TU_CLAVE`. Reemplázalos por tus datos reales. |
| `El sitio rechazo el acceso` | Tu documento o clave están mal escritos, o la clave caducó. Pruébalos primero en la página de la PNP desde el navegador. |
| No aparecen `Dockerfile` ni `checker.py` al escribir `ls` | La terminal está en otra carpeta. Repite el paso 5.1. |
| Nunca llega ninguna notificación | El nombre secreto no coincide entre `.env.local` y la app ntfy. Compáralos letra por letra. |
| Llegó "MONITOR AVERIADO" | Casi siempre la clave de la PNP caducó. Entra a la página desde el navegador, cámbiala si hace falta, actualiza `.env.local` y ejecuta `docker compose up -d --build`. |
| Dejó de avisar sin más | Comprueba que la computadora no se haya suspendido y que Docker Desktop siga abierto. |

Si necesitas empezar de cero, ejecuta `docker compose down` y repite desde el
paso 5.2. Tu archivo `.env.local` no se borra.

---

## Privacidad

- Tu documento y tu clave se quedan **solo en tu computadora**, dentro de
  `.env.local`. No se envían a ningún servidor nuestro ni a GitHub.
- Las revisiones salen desde **tu propia conexión a internet**, igual que si
  entraras a la página tú mismo desde el navegador.
- Las notificaciones viajan por ntfy.sh usando tu nombre secreto. Por eso
  importa que sea difícil de adivinar y que no lo compartas.
- Si le pasas este programa a un familiar, **cada persona debe inventar su
  propio nombre secreto**. Si comparten el mismo, comparten las notificaciones.
- El programa solo consulta y avisa. Nunca reserva citas ni modifica nada en la
  página de la PNP.
