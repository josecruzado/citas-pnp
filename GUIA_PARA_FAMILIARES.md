# Monitor de citas PNP: instalación para familiares

Este monitor consulta el sistema de citas desde tu propia conexión de internet y te
envía un aviso a tu celular mediante **ntfy** cuando encuentra cupos. No reserva
citas y no envía información a GitHub.

Cada persona debe instalar su propia copia y usar **sus propias credenciales PNP**.
No compartas tu archivo `.env.local`, DNI, clave ni tema de ntfy.

## Antes de empezar

Necesitas:

- Una computadora en Perú con internet que pueda quedar encendida.
- Docker Desktop.
- La aplicación **ntfy** en Android o iPhone.
- Tu DNI/credencial y clave del sistema de citas PNP.

## 1. Descargar el proyecto desde GitHub

1. En la página del repositorio, pulsa **Code** → **Download ZIP**.
2. Descomprime el ZIP en una carpeta fácil de encontrar, por ejemplo
   `Documentos/monitor-citas-pnp`.

No hace falta instalar Python, Chromium ni Git: Docker los mantiene aislados dentro
del contenedor.

## 2. Instalar Docker Desktop

### macOS

1. Descarga e instala [Docker Desktop para Mac](https://www.docker.com/products/docker-desktop/).
2. Ábrelo y espera a que indique que Docker está en ejecución.
3. En Docker Desktop → **Settings** → **General**, activa **Start Docker Desktop when you log in**.

### Windows 10/11

1. Descarga e instala [Docker Desktop para Windows](https://www.docker.com/products/docker-desktop/).
2. Durante la instalación acepta usar WSL 2 si te lo solicita.
3. Ábrelo y espera a que indique que Docker está en ejecución.
4. En Docker Desktop → **Settings** → **General**, activa **Start Docker Desktop when you sign in**.

## 3. Crear tu configuración privada

Abre una terminal dentro de la carpeta que descomprimiste.

En macOS: abre **Terminal**, escribe `cd ` (con espacio), arrastra la carpeta a la
ventana y pulsa Enter.

En Windows: abre la carpeta en el Explorador, haz clic derecho en un espacio vacío y
elige **Open in Terminal**.

Ejecuta uno de estos comandos:

```bash
# macOS
cp .env.local.example .env.local
```

```powershell
# Windows PowerShell
Copy-Item .env.local.example .env.local
```

Abre `.env.local` con un editor de texto y completa:

```dotenv
PNP_DNI=TU_DOCUMENTO
PNP_CLAVE=TU_CLAVE
PNP_TIPO_DOC=1
SEDE=1
FECHA_OBJETIVO=
NTFY_TOPIC=un-nombre-largo-y-dificil-de-adivinar
INTERVALO_MIN=5
PUBLICAR=0
```

`NTFY_TOPIC` es el canal de tus alertas. Inventa uno largo y privado, por ejemplo
`citas-familia-a91c8e2d7f4b`. Nadie que no conozca ese nombre debería suscribirse.

Si ya tienes una cita y solo buscas una anterior, escribe su fecha en
`FECHA_OBJETIVO` como `AAAA-MM-DD`.

## 4. Activar las alertas en el celular

1. Instala **ntfy** desde App Store o Google Play.
2. Pulsa `+` para suscribirte.
3. Pega exactamente el valor de `NTFY_TOPIC`.
4. Permite notificaciones cuando el celular lo solicite.

## 5. Iniciar el monitor

En la terminal, dentro de la carpeta del proyecto, ejecuta:

```bash
docker compose up -d --build
```

La primera vez puede tardar varios minutos porque Docker descarga Chromium. Después
el monitor se revisa automáticamente cada cinco minutos.

Para comprobarlo:

```bash
docker compose logs -f monitor-citas
```

Debes ver mensajes como `Sesion iniciada` y `Fechas con cupo`. Para dejar de ver los
mensajes sin detener el monitor, pulsa `Ctrl+C`.

## Mantenerlo activo siempre

No necesitas dejar la terminal abierta. El contenedor usa reinicio automático.

- Deja Docker Desktop iniciado.
- Mantén el equipo encendido, conectado a internet y sin reposo.
- En laptops, conéctala a corriente y ajusta el sistema para que no entre en reposo.

Cuando se reinicie el equipo, Docker Desktop iniciará el monitor automáticamente.

## Comandos útiles

```bash
# Ver si está activo
docker compose ps

# Ver las últimas revisiones
docker compose logs --tail=50 monitor-citas

# Detenerlo temporalmente
docker compose stop

# Volver a iniciarlo
docker compose start

# Actualizarlo después de descargar una versión nueva
docker compose up -d --build
```

## Seguridad y privacidad

- El archivo `.env.local` contiene información privada y está excluido de Git.
- Nunca lo subas a GitHub ni lo envíes por WhatsApp o correo.
- Cada instalación solo consulta y avisa; la reserva se hace manualmente en PNP,
  porque el sitio solicita captcha.
- El monitor no usa GitHub para operar ni actualiza una página web.
