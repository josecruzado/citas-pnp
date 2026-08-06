#!/usr/bin/env bash
# =============================================================================
#  REVISION LOCAL  ·  Alerta de Citas PNP
# =============================================================================
#  Ejecuta checker.py desde TU conexion (el sitio de la PNP rechaza IPs de
#  centros de datos extranjeros) y publica web/estado.json en el repositorio,
#  para que la pagina de Vercel se actualice igual que antes.
#
#  Primera vez:
#      cp .env.local.example .env.local     # y completalo
#      chmod +x run_local.sh
#      ./run_local.sh --once                # prueba una revision
#
#  Vigilancia continua:
#      ./run_local.sh                       # bucle, cada N minutos
#
#  Para cron / Programador de tareas: usa --once
# =============================================================================

set -uo pipefail
cd "$(dirname "$0")"

VERDE=$'\033[0;32m'; ROJO=$'\033[0;31m'; AMAR=$'\033[0;33m'; FIN=$'\033[0m'
log()  { echo "$(date '+%d/%m %H:%M:%S')  $1"; }
ok()   { log "${VERDE}✓${FIN} $1"; }
err()  { log "${ROJO}✗${FIN} $1"; }
warn() { log "${AMAR}!${FIN} $1"; }

# --- configuracion --------------------------------------------------------- #

if [ ! -f .env.local ]; then
  err "Falta .env.local. Copia .env.local.example y completalo."
  exit 1
fi
set -a; source .env.local; set +a

: "${PNP_DNI:?Falta PNP_DNI en .env.local}"
: "${PNP_CLAVE:?Falta PNP_CLAVE en .env.local}"
INTERVALO_MIN="${INTERVALO_MIN:-5}"
# PUBLICAR_DOCKER permite que Compose fuerce la publicación sin modificar .env.local.
PUBLICAR="${PUBLICAR_DOCKER:-${PUBLICAR:-1}}"

PY="$(command -v python3 || command -v python)"
[ -n "$PY" ] || { err "No encuentro Python."; exit 1; }

# --- una revision ---------------------------------------------------------- #

revisar() {
  "$PY" checker.py
  local rc=$?
  [ $rc -eq 0 ] || { err "checker.py termino con codigo $rc"; return 1; }

  [ "$PUBLICAR" = "1" ] || return 0
  [ -d .git ] || { warn "No es un repositorio git; no publico."; return 0; }

  # Traer cambios remotos sin romper si hay commits nuevos
  git fetch --quiet origin 2>/dev/null || true
  git rebase --quiet "origin/$(git rev-parse --abbrev-ref HEAD)" 2>/dev/null \
    || git rebase --abort 2>/dev/null || true

  git add web/estado.json
  if git diff --staged --quiet; then
    log "Sin cambios en el estado."
    return 0
  fi

  git -c user.name="monitor-citas" \
      -c user.email="monitor-citas@local" \
      commit -q -m "estado: $(date -u '+%Y-%m-%d %H:%M UTC')"

  if git push --quiet origin HEAD 2>/dev/null; then
    ok "Estado publicado"
  else
    warn "No pude publicar (revisa tu acceso a GitHub). El commit quedo local."
  fi
}

# --- modo --------------------------------------------------------------- #

if [ "${1:-}" = "--once" ]; then
  revisar
  exit $?
fi

cat <<EOF

  Monitor de citas · revision local
  Intervalo: ${INTERVALO_MIN} min   ·   Publicar en GitHub: $([ "$PUBLICAR" = "1" ] && echo si || echo no)
  Ctrl+C para detener.

EOF

trap 'echo; log "Detenido."; exit 0' INT TERM

FALLOS=0
while true; do
  if revisar; then
    FALLOS=0
  else
    FALLOS=$((FALLOS + 1))
    if [ "$FALLOS" -ge 3 ]; then
      ESPERA=$(( 120 * 2 ** (FALLOS - 3) ))
      [ "$ESPERA" -gt 1800 ] && ESPERA=1800
      warn "${FALLOS} fallos seguidos; espero ${ESPERA}s."
      sleep "$ESPERA"
      continue
    fi
  fi
  PAUSA=$(( INTERVALO_MIN * 60 + RANDOM % 45 ))
  log "Siguiente revision en $(( PAUSA / 60 )) min."
  sleep "$PAUSA"
done
