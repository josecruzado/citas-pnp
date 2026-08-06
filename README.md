# Alerta de citas PNP · Lunas oscurecidas

Este proyecto revisa automáticamente si hay citas disponibles para **Lunas
Oscurecidas** de la Policía Nacional del Perú y te avisa al celular mediante
**ntfy** cuando aparece un cupo.

Funciona desde tu propia computadora y tu propia conexión a internet en Perú.
No usa GitHub Actions, no publica información en una web y no reserva citas.
La reserva siempre la haces tú en la página de la PNP, donde se solicita captcha.

## Antes de empezar

Necesitas:

- Una PC con Windows 10/11 o una Mac conectada a internet.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/).
- La app **ntfy** instalada en tu Android o iPhone.
- Tu documento y clave del sistema de citas PNP.

> La computadora debe permanecer encendida, con Docker Desktop abierto y sin entrar
> en reposo para que el monitor continúe revisando las citas.

## 1. Descargar el proyecto

En GitHub pulsa **Code** → **Download ZIP** y descomprime el archivo en una carpeta,
por ejemplo `Documentos/monitor-citas-pnp`.

No necesitas instalar Python, Playwright ni Chromium: Docker los ejecuta de forma
aislada dentro del contenedor.

## 2. Instalar y preparar Docker Desktop

Descarga Docker Desktop para tu sistema operativo, instálalo y ábrelo. Espera a que
indique que Docker está funcionando.

Para que el monitor se recupere después de reiniciar la computadora, activa esta
opción en Docker Desktop:

- **macOS:** Settings → General → *Start Docker Desktop when you log in*.
- **Windows:** Settings → General → *Start Docker Desktop when you sign in*.

En una laptop, déjala conectada a la corriente y configura el sistema para evitar el
reposo mientras esté funcionando.

## 3. Crear tu configuración privada

Abre una terminal dentro de la carpeta que descomprimiste.

- **macOS:** abre Terminal, escribe `cd ` (con un espacio), arrastra la carpeta a la
  ventana y pulsa Enter.
- **Windows:** abre la carpeta en el Explorador, haz clic derecho en un espacio vacío
  y elige **Open in Terminal**.

Luego crea tu archivo privado de configuración:

```bash
# macOS
cp .env.local.example .env.local
```

```powershell
# Windows PowerShell
Copy-Item .env.local.example .env.local
```

Abre el archivo `.env.local` con Bloc de notas, TextEdit en modo texto plano o VS Code
y completa los valores:

```dotenv
PNP_DNI=TU_DOCUMENTO
PNP_CLAVE=TU_CLAVE
PNP_TIPO_DOC=1
SEDE=1
FECHA_OBJETIVO=
NTFY_TOPIC=un-tema-largo-y-dificil-de-adivinar
INTERVALO_MIN=5
```

Notas:

- `PNP_TIPO_DOC=1` es DNI; usa `2` para carnet de extranjería.
- `SEDE=1` corresponde a Lima–La Victoria. Cámbialo si la PNP te indica otro código.
- Deja `FECHA_OBJETIVO` vacío para recibir cualquier cita. Si ya tienes una cita y
  buscas una más próxima, escribe la fecha actual como `AAAA-MM-DD`.
- Para `NTFY_TOPIC`, inventa un nombre largo y difícil de adivinar, por ejemplo
  `citas-familia-7d92a1f4b8`. Ese será tu canal privado de alertas.

Nunca compartas `.env.local`: contiene tus credenciales PNP.

## 4. Configurar ntfy en el celular

1. Instala **ntfy** desde App Store o Google Play.
2. Abre la app y pulsa `+` para añadir una suscripción.
3. Escribe exactamente el mismo valor que colocaste en `NTFY_TOPIC`.
4. Permite las notificaciones cuando el celular las solicite.

## 5. Iniciar el monitor

En la misma terminal ejecuta:

```bash
docker compose up -d --build
```

La primera instalación tarda algunos minutos porque Docker descarga Chromium. Al
terminar, el monitor revisa el sistema PNP cada cinco minutos y se reinicia solo si
Docker Desktop o la computadora se reinician.

Para confirmar que funciona:

```bash
docker compose logs -f monitor-citas
```

Debes ver mensajes parecidos a:

```text
Sesion iniciada.
Fechas con cupo: 0 | Sin Cupos
Sin cupos por ahora.
```

Pulsa `Ctrl+C` para dejar de ver los mensajes; **no** detiene el monitor.

## Cómo llegan las alertas

Cuando aparezca al menos una fecha con cupo, ntfy enviará una notificación push al
celular con la fecha, horarios disponibles y el número de cupos. Al tocarla podrás
abrir la página de citas PNP.

El monitor evita repetir el mismo aviso: solo vuelve a alertar cuando cambian las
fechas encontradas. Si no hay cupos, no envía notificaciones.

## Comandos útiles

```bash
# Confirmar que el monitor está activo
docker compose ps

# Ver las últimas revisiones
docker compose logs --tail=50 monitor-citas

# Detenerlo temporalmente
docker compose stop

# Volver a iniciarlo
docker compose start

# Aplicar una actualización del proyecto
docker compose up -d --build

# Eliminar el contenedor (no elimina tu archivo .env.local)
docker compose down
```

## Privacidad y límites

- Las credenciales permanecen solo en tu computadora, dentro de `.env.local`.
- El monitor no usa GitHub ni una página web durante su funcionamiento.
- La disponibilidad puede cambiar en segundos; una alerta no garantiza que el cupo
  siga libre cuando abras el sistema.
- La PNP solicita captcha para reservar, por lo que este proyecto solo consulta y
  avisa.
