#!/usr/bin/env bash
# =============================================================================
#  DESPLIEGUE AUTOMATICO  ·  Alerta de Citas PNP
# =============================================================================
#  Crea el repositorio en tu GitHub, carga los secrets, sube el proyecto y
#  lanza la primera revision. Despues solo te queda conectar Vercel.
#
#  Requisitos:
#     - git
#     - GitHub CLI (gh)  ->  https://cli.github.com
#
#  Uso:
#     chmod +x deploy.sh
#     ./deploy.sh
#
#  En Windows: usa Git Bash o WSL.
# =============================================================================

set -euo pipefail

VERDE=$'\033[0;32m'; ROJO=$'\033[0;31m'; AMAR=$'\033[0;33m'
AZUL=$'\033[0;36m';  NEG=$'\033[1m';    FIN=$'\033[0m'

ok()   { echo "${VERDE}  ✓${FIN} $1"; }
info() { echo "${AZUL}  →${FIN} $1"; }
warn() { echo "${AMAR}  !${FIN} $1"; }
err()  { echo "${ROJO}  ✗${FIN} $1" >&2; }
titulo() { echo; echo "${NEG}$1${FIN}"; echo "${NEG}$(printf '─%.0s' $(seq 1 ${#1}))${FIN}"; }

abortar() { err "$1"; exit 1; }

# --------------------------------------------------------------------------- #
clear || true
cat <<'BANNER'

  ╔══════════════════════════════════════════════════════════╗
  ║   ALERTA DE CITAS  ·  Lunas Oscurecidas (PNP)            ║
  ║   Despliegue automatico en GitHub                        ║
  ╚══════════════════════════════════════════════════════════╝

BANNER

# --------------------------------------------------------------------------- #
titulo "1. Comprobando herramientas"

command -v git >/dev/null 2>&1 || abortar "Falta git. Instalalo desde https://git-scm.com"
ok "git encontrado"

if ! command -v gh >/dev/null 2>&1; then
  err "Falta GitHub CLI (gh)."
  echo
  echo "  Instalalo asi:"
  echo "    macOS          brew install gh"
  echo "    Ubuntu/Debian  sudo apt install gh"
  echo "    Windows        winget install GitHub.cli"
  echo "    Otros          https://cli.github.com"
  exit 1
fi
ok "gh encontrado"

if ! gh auth status >/dev/null 2>&1; then
  warn "No has iniciado sesion en GitHub."
  info "Abriendo el login de gh (se hace en tu navegador)..."
  echo
  gh auth login || abortar "No se completo el inicio de sesion."
fi

USUARIO="$(gh api user --jq .login)"
[ -n "$USUARIO" ] || abortar "No pude leer tu usuario de GitHub."
ok "Sesion activa como ${NEG}${USUARIO}${FIN}"

# --------------------------------------------------------------------------- #
titulo "2. Comprobando los archivos del proyecto"

for f in checker.py .github/workflows/citas.yml web/index.html vercel.json; do
  [ -f "$f" ] || abortar "No encuentro '$f'. Ejecuta el script desde la carpeta del proyecto."
done
ok "Todos los archivos presentes"

# --------------------------------------------------------------------------- #
titulo "3. Datos del despliegue"

read -rp "  Nombre del repositorio [citas-pnp]: " REPO
REPO="${REPO:-citas-pnp}"

if gh repo view "$USUARIO/$REPO" >/dev/null 2>&1; then
  warn "El repositorio '$USUARIO/$REPO' ya existe."
  read -rp "  ¿Subir el proyecto ahi de todas formas? (s/N): " R
  [[ "$R" =~ ^[sS]$ ]] || abortar "Cancelado. Elige otro nombre y vuelve a ejecutar."
  REPO_EXISTE=1
else
  REPO_EXISTE=0
fi

echo
echo "  El repositorio sera ${NEG}publico${FIN}: GitHub Actions solo es ilimitado"
echo "  en repos publicos, y el monitor necesita correr cada 5 minutos."
echo "  No se publica nada sensible: tus claves van en secrets cifrados."
echo

# ---- tema ntfy ----
TEMA_SUGERIDO="citas-pnp-$(head -c 5 /dev/urandom | od -An -tx1 | tr -d ' \n')"
echo "  Tema de ntfy (el canal por el que llegan los avisos al movil)."
echo "  Debe ser dificil de adivinar: quien lo sepa vera las alertas."
read -rp "  Tema [$TEMA_SUGERIDO]: " TEMA
TEMA="${TEMA:-$TEMA_SUGERIDO}"

# ---- credenciales ----
echo
echo "  Tus credenciales del sistema PNP. Se guardan como ${NEG}secrets cifrados${FIN}"
echo "  en tu propio repositorio; nadie mas puede leerlas."
echo
read -rp "  Nro. de documento: " DNI
[ -n "$DNI" ] || abortar "El documento es obligatorio."
read -rsp "  Clave: " CLAVE; echo
[ -n "$CLAVE" ] || abortar "La clave es obligatoria."

echo
read -rp "  Tipo de documento  1=DNI  2=Carnet [1]: " TIPO; TIPO="${TIPO:-1}"
read -rp "  Codigo de sede [1]: " SEDE; SEDE="${SEDE:-1}"
echo
echo "  Si ya tienes cita y solo quieres una mas proxima, escribe su fecha"
echo "  (AAAA-MM-DD). Solo se avisara de cupos anteriores. Enter = cualquiera."
read -rp "  Tu cita actual: " OBJETIVO

# --------------------------------------------------------------------------- #
titulo "4. Preparando los archivos"

# Personalizar index.html
python3 - "$USUARIO" "$REPO" "$TEMA" <<'PY' || abortar "No pude personalizar web/index.html"
import re, sys, pathlib
usuario, repo, tema = sys.argv[1:4]
p = pathlib.Path("web/index.html")
s = p.read_text(encoding="utf-8")
s = re.sub(r'const USUARIO_REPO = "[^"]*";', f'const USUARIO_REPO = "{usuario}";', s)
s = re.sub(r'const NOMBRE_REPO  = "[^"]*";', f'const NOMBRE_REPO  = "{repo}";', s)
s = re.sub(r'const TEMA_NTFY    = "[^"]*";', f'const TEMA_NTFY    = "{tema}";', s)
p.write_text(s, encoding="utf-8")
PY
ok "web/index.html personalizado"

cat > .gitignore <<'EOF'
__pycache__/
*.pyc
config_citas.json
estado_citas.json
alerta_citas.log
capturas/
.env
EOF
ok ".gitignore creado"

if [ ! -d .git ]; then
  git init -q
  git branch -M main
  ok "Repositorio git inicializado"
else
  git branch -M main 2>/dev/null || true
  ok "Repositorio git ya existente"
fi

git add -A
if git diff --staged --quiet 2>/dev/null; then
  info "Sin cambios que registrar"
else
  git -c user.name="${USUARIO}" \
      -c user.email="${USUARIO}@users.noreply.github.com" \
      commit -q -m "Monitor de citas PNP: despliegue inicial"
  ok "Commit creado"
fi

# --------------------------------------------------------------------------- #
titulo "5. Subiendo a GitHub"

if [ "$REPO_EXISTE" -eq 0 ]; then
  gh repo create "$REPO" --public --source=. --remote=origin --push \
    --description "Monitor de citas para lunas oscurecidas (PNP)" \
    || abortar "No pude crear el repositorio."
  ok "Repositorio creado y subido"
else
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/$USUARIO/$REPO.git"
  git push -u origin main --force-with-lease \
    || abortar "No pude subir. Revisa si el repo remoto tiene commits distintos."
  ok "Proyecto subido"
fi

# --------------------------------------------------------------------------- #
titulo "6. Cargando secrets y variables"

gh secret set PNP_DNI   --repo "$USUARIO/$REPO" --body "$DNI"   && ok "PNP_DNI"
gh secret set PNP_CLAVE --repo "$USUARIO/$REPO" --body "$CLAVE" && ok "PNP_CLAVE"
gh secret set NTFY_TOPIC --repo "$USUARIO/$REPO" --body "$TEMA" && ok "NTFY_TOPIC"
unset CLAVE DNI

gh variable set PNP_TIPO_DOC --repo "$USUARIO/$REPO" --body "$TIPO" >/dev/null && ok "PNP_TIPO_DOC"
gh variable set SEDE         --repo "$USUARIO/$REPO" --body "$SEDE" >/dev/null && ok "SEDE"
if [ -n "${OBJETIVO:-}" ]; then
  gh variable set FECHA_OBJETIVO --repo "$USUARIO/$REPO" --body "$OBJETIVO" >/dev/null && ok "FECHA_OBJETIVO"
fi

# --------------------------------------------------------------------------- #
titulo "7. Lanzando la primera revision"

sleep 4
if gh workflow run citas.yml --repo "$USUARIO/$REPO" >/dev/null 2>&1; then
  ok "Revision lanzada"
  info "Tarda un par de minutos (instala Chromium la primera vez)."
else
  warn "No pude lanzarla automaticamente."
  info "Hazlo desde: https://github.com/$USUARIO/$REPO/actions"
fi

# --------------------------------------------------------------------------- #
titulo "Listo"

cat <<FIN_MSG

  ${VERDE}El monitor ya esta desplegado.${FIN}

  ${NEG}Repositorio${FIN}   https://github.com/$USUARIO/$REPO
  ${NEG}Revisiones${FIN}    https://github.com/$USUARIO/$REPO/actions
  ${NEG}Tema ntfy${FIN}     $TEMA

  ${NEG}Te quedan dos pasos manuales:${FIN}

  ${AZUL}1. Conectar Vercel${FIN}
     Entra a https://vercel.com/new
     Importa el repositorio '$REPO' y pulsa Deploy.
     La configuracion ya viene en vercel.json: no toques nada.

  ${AZUL}2. Suscribirte en el movil${FIN}
     Instala la app 'ntfy' (App Store / Google Play)
     Pulsa '+' y pega:  ${NEG}$TEMA${FIN}

  Para comprobar que las alertas llegan, con la app ya suscrita:

     curl -d "Prueba de alerta" ntfy.sh/$TEMA

FIN_MSG
