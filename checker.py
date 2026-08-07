#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  CHECKER  ·  Monitor de citas Lunas Oscurecidas (PNP)
================================================================================

  Se ejecuta cada pocos minutos dentro de Docker, desde la conexion del usuario.
  Consulta el sistema de citas con UNA sola cuenta y, si hay cupo, difunde un
  aviso push a todos los suscriptores via ntfy.

  Los usuarios NUNCA entregan sus credenciales: los cupos son los mismos para
  todos, asi que basta una cuenta para consultarlos.

  Variables de entorno (.env.local):
      PNP_DNI          documento del operador          (obligatorio)
      PNP_CLAVE        clave del operador              (obligatorio)
      NTFY_TOPIC       tema publico de difusion        (obligatorio)
      PNP_TIPO_DOC     1 = DNI, 2 = carnet             (por defecto 1)
      SEDE             codigo de sede                  (por defecto 1)
      FECHA_OBJETIVO   AAAA-MM-DD, avisa solo si es antes  (opcional)
      NTFY_SERVER      servidor ntfy                   (por defecto ntfy.sh)

  Salida: datos/estado.json  ·  codigo 0 si la revision se completo,
          1 si falta configuracion, 2 si la revision fallo (activa el
          backoff de run_local.sh).

  El monitor tambien avisa cuando el que falla es el propio monitor: tras
  varios errores seguidos manda una alerta, otra al recuperarse, y un latido
  diario para que el silencio nunca sea ambiguo.
================================================================================
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

# --------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).resolve().parent
DATOS = BASE_DIR / "datos"
ESTADO = DATOS / "estado.json"

# Cuantos fallos seguidos antes de avisar que el monitor esta roto, y cada
# cuanto mandar el latido de "sigo vivo".
FALLOS_PARA_AVISAR = 3
HORAS_ENTRE_LATIDOS = 24

URL_LOGIN = "https://sistemas.policia.gob.pe/lunasoscurecidas/Solicitud_Menu.aspx"

SEL_TIPO_DOC  = "#DdlDocumento"
SEL_DOC       = "#TxtCIP"
SEL_CLAVE     = "#TxtClave"
SEL_LOGIN_BTN = "#BtnContinuar"
SEL_LOGIN_MSG = "#LblMensaje"
SEL_BTN_VER   = "#MainContent_gvProgramacion_btnAccion_0"
SEL_BTN_CITA  = "#MainContent_btnCita"
SEL_SEDE      = "#MainContent_idUcitas_cbosede"
SEL_FECHA     = "#MainContent_idUcitas_cboFecha"
SEL_HORA      = "#MainContent_idUcitas_cboHora"
SEL_CUPOS     = "#MainContent_idUcitas_lblcupos"

RE_VACIO = re.compile(r"sin\s*cupos|seleccione|no\s*hay|^-+$", re.IGNORECASE)

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9,
         "octubre": 10, "noviembre": 11, "diciembre": 12}

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

TIMEOUT = 45_000

ENV = {
    "dni": os.environ.get("PNP_DNI", "").strip(),
    "clave": os.environ.get("PNP_CLAVE", "").strip(),
    "tipo_doc": os.environ.get("PNP_TIPO_DOC", "1").strip(),
    "sede": os.environ.get("SEDE", "1").strip(),
    "objetivo": os.environ.get("FECHA_OBJETIVO", "").strip(),
    "ntfy_topic": os.environ.get("NTFY_TOPIC", "").strip(),
    "ntfy_server": os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
}


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------- #

def sin_tildes(s: str) -> str:
    return s.translate(str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN"))


def parse_fecha(txt: str) -> date | None:
    if not txt:
        return None
    t = txt.strip()
    for patron, orden in ((r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", (0, 1, 2)),
                          (r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", (2, 1, 0))):
        m = re.search(patron, t)
        if m:
            g = m.groups()
            try:
                return date(int(g[orden[0]]), int(g[orden[1]]), int(g[orden[2]]))
            except ValueError:
                pass
    m = re.search(r"(\d{1,2})\s*(?:de\s+)?([a-zA-ZáéíóúÁÉÍÓÚ]{4,})\s*(?:de\s+)?(\d{4})",
                  t, re.IGNORECASE)
    if m:
        mes = MESES.get(sin_tildes(m.group(2)).lower())
        if mes:
            try:
                return date(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                pass
    return None


# --------------------------------------------------------------------------- #

def _postback(page, selector: str) -> None:
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=TIMEOUT):
            page.click(selector)
    except PWTimeout:
        page.wait_for_load_state("networkidle", timeout=TIMEOUT)


def login(page) -> None:
    page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=TIMEOUT)
    page.wait_for_selector(SEL_DOC, timeout=TIMEOUT)
    page.select_option(SEL_TIPO_DOC, ENV["tipo_doc"])
    page.fill(SEL_DOC, ENV["dni"])
    page.fill(SEL_CLAVE, ENV["clave"])
    _postback(page, SEL_LOGIN_BTN)

    if page.locator(SEL_LOGIN_MSG).count():
        msg = (page.locator(SEL_LOGIN_MSG).first.inner_text() or "").strip()
        if msg:
            raise RuntimeError(f"El sitio rechazo el acceso: {msg}")
    if page.locator(SEL_CLAVE).count() and page.locator(SEL_LOGIN_BTN).count():
        raise RuntimeError("Sigue en la pantalla de login.")
    log("Sesion iniciada.")


def abrir_formulario(page):
    page.wait_for_selector(SEL_BTN_VER, timeout=TIMEOUT)
    _postback(page, SEL_BTN_VER)
    page.wait_for_selector(SEL_BTN_CITA, timeout=TIMEOUT)

    destino = page
    try:
        with page.context.expect_page(timeout=8_000) as info:
            page.click(SEL_BTN_CITA)
        destino = info.value
        destino.wait_for_load_state("domcontentloaded", timeout=TIMEOUT)
    except PWTimeout:
        destino.wait_for_load_state("networkidle", timeout=TIMEOUT)

    destino.wait_for_selector(SEL_SEDE, timeout=TIMEOUT)
    return destino


def _opciones(page, selector: str) -> list[dict]:
    if not page.locator(selector).count():
        return []
    return page.eval_on_selector_all(
        f"{selector} option",
        "els => els.map(e => ({value: e.value, text: (e.textContent||'').trim()}))")


def _reales(ops: list[dict]) -> list[dict]:
    out = []
    for o in ops:
        v, t = (o.get("value") or "").strip(), (o.get("text") or "").strip()
        if v in ("", "0", "00", "-1") or not t or RE_VACIO.search(t):
            continue
        out.append({"value": v, "text": t})
    return out


def buscar_cupos(page) -> list[dict]:
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=TIMEOUT):
            page.select_option(SEL_SEDE, ENV["sede"])
    except PWTimeout:
        page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    page.wait_for_timeout(1500)

    fechas = _reales(_opciones(page, SEL_FECHA))
    etiqueta = ""
    if page.locator(SEL_CUPOS).count():
        etiqueta = (page.locator(SEL_CUPOS).first.inner_text() or "").strip()
    log(f"Fechas con cupo: {len(fechas)}  |  {etiqueta or '-'}")

    salida = []
    for f in fechas:
        item = {"fecha": f["text"], "horas": [], "cupos": etiqueta}
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
                page.select_option(SEL_FECHA, f["value"])
            page.wait_for_timeout(1000)
            item["horas"] = [h["text"] for h in _reales(_opciones(page, SEL_HORA))]
            if page.locator(SEL_CUPOS).count():
                item["cupos"] = (page.locator(SEL_CUPOS).first.inner_text() or "").strip()
        except Exception as e:  # noqa: BLE001
            log(f"Sin detalle de horas para {f['text']}: {e}")
        salida.append(item)
    return salida


def filtrar(cupos: list[dict]) -> list[dict]:
    objetivo = parse_fecha(ENV["objetivo"])
    if not objetivo:
        return cupos
    utiles = [c for c in cupos
              if (parse_fecha(c["fecha"]) is None or parse_fecha(c["fecha"]) < objetivo)]
    if len(utiles) < len(cupos):
        log(f"Ignoro {len(cupos) - len(utiles)} cupo(s) posteriores a {objetivo}.")
    return utiles


# --------------------------------------------------------------------------- #

def enviar_ntfy(titulo: str, cuerpo: str, prioridad: str, tags: str) -> bool:
    if not ENV["ntfy_topic"]:
        log("Sin NTFY_TOPIC: no difundo aviso.")
        return False
    try:
        r = requests.post(
            f"{ENV['ntfy_server']}/{ENV['ntfy_topic']}",
            data=cuerpo.encode("utf-8"),
            headers={"Title": titulo.encode("utf-8"),
                     "Priority": prioridad,
                     "Tags": tags,
                     "Click": URL_LOGIN,
                     "Actions": f"view, Abrir sistema, {URL_LOGIN}"},
            timeout=25)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: ntfy fallo: {e}")
        return False


def avisar_cupos(cupos: list[dict]) -> None:
    lineas = []
    for c in cupos:
        horas = ", ".join(c["horas"][:8]) if c["horas"] else "(ver en el sitio)"
        lineas.append(f"* {c['fecha']}\n  Horas: {horas}\n  Cupos: {c['cupos']}")
    cuerpo = ("HAY CUPO DE CITA DISPONIBLE\n\n" + "\n\n".join(lineas) +
              "\n\nEntra YA y reserva. El formulario te pedira un captcha.")
    if enviar_ntfy("CUPO DE CITA DISPONIBLE", cuerpo, "urgent", "rotating_light"):
        log("Aviso difundido por ntfy.")


def avisar_averiado(fallos: int, detalle: str) -> None:
    cuerpo = (f"El monitor lleva {fallos} revisiones seguidas fallando y no "
              f"puede comprobar si hay citas.\n\nUltimo error:\n{detalle}\n\n"
              "Suele deberse a que la clave PNP caduco o a que el sitio cambio. "
              "Revisa los registros con:\n"
              "docker compose logs --tail=50 monitor-citas")
    if enviar_ntfy("MONITOR AVERIADO", cuerpo, "high", "warning"):
        log("Aviso de averia difundido por ntfy.")


def avisar_recuperado() -> None:
    if enviar_ntfy("Monitor recuperado",
                   "El monitor volvio a revisar las citas con normalidad.",
                   "default", "white_check_mark"):
        log("Aviso de recuperacion difundido por ntfy.")


def toca_latido(previo: dict) -> bool:
    ultimo = previo.get("ultimo_latido")
    if not ultimo:
        return True
    try:
        marca = datetime.fromisoformat(ultimo)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - marca >= timedelta(hours=HORAS_ENTRE_LATIDOS)


def enviar_latido(revisiones: int) -> bool:
    cuerpo = (f"El monitor sigue funcionando. Lleva {revisiones} revisiones.\n"
              "Si hubiera un cupo, ya te habria avisado.")
    if enviar_ntfy("Monitor activo", cuerpo, "low", "heartbeat"):
        log("Latido diario difundido por ntfy.")
        return True
    return False


def leer_estado_previo() -> dict:
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def escribir_estado(datos: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atomica: un corte a media escritura no deja el JSON a medias.
    temporal = ESTADO.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporal, ESTADO)
    log(f"Estado guardado en {ESTADO.relative_to(BASE_DIR)}")


# --------------------------------------------------------------------------- #

def main() -> int:
    faltan = [nombre for nombre, clave in (("PNP_DNI", "dni"),
                                           ("PNP_CLAVE", "clave"),
                                           ("NTFY_TOPIC", "ntfy_topic"))
              if not ENV[clave]]
    if faltan:
        log(f"ERROR: falta configurar en .env.local: {', '.join(faltan)}")
        return 1

    previo = leer_estado_previo()
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fallos_previos = int(previo.get("fallos_seguidos", 0))
    salida = {"actualizado": ahora, "sede": ENV["sede"],
              "objetivo": ENV["objetivo"], "hay_cupo": False,
              "cupos": [], "error": None,
              "revisiones": int(previo.get("revisiones", 0)) + 1,
              "fallos_seguidos": 0,
              "ultimo_latido": previo.get("ultimo_latido")}
    fallo = False

    try:
        with sync_playwright() as pw:
            navegador = pw.chromium.launch(
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
            ctx = navegador.new_context(user_agent=USER_AGENT, locale="es-PE",
                                        viewport={"width": 1366, "height": 900})
            ctx.set_default_timeout(TIMEOUT)
            page = ctx.new_page()
            try:
                login(page)
                cupos = filtrar(buscar_cupos(abrir_formulario(page)))
            finally:
                ctx.close()
                navegador.close()

        salida["cupos"] = cupos
        salida["hay_cupo"] = bool(cupos)

        # La huella incluye horas y cupos: si cambia la oferta de una misma
        # fecha, vuelve a avisar en lugar de callarse.
        def huella(lista: list[dict]) -> list:
            return sorted([c["fecha"], c.get("cupos", ""), tuple(c.get("horas", []))]
                          for c in lista)

        if cupos and huella(cupos) != huella(previo.get("cupos", [])):
            log("*** CUPO NUEVO DETECTADO ***")
            avisar_cupos(cupos)
        elif cupos:
            log("Mismos cupos que la revision anterior; no repito el aviso.")
        else:
            log("Sin cupos por ahora.")

        if fallos_previos >= FALLOS_PARA_AVISAR:
            avisar_recuperado()

    except Exception as e:  # noqa: BLE001
        fallo = True
        log(f"ERROR en la revision: {e}")
        salida["error"] = str(e)[:300]
        salida["cupos"] = previo.get("cupos", [])
        salida["hay_cupo"] = bool(salida["cupos"])
        salida["fallos_seguidos"] = fallos_previos + 1
        # Un solo aviso al cruzar el umbral: ni silencio eterno ni spam.
        if salida["fallos_seguidos"] == FALLOS_PARA_AVISAR:
            avisar_averiado(salida["fallos_seguidos"], salida["error"])

    if not fallo and toca_latido(previo) and enviar_latido(salida["revisiones"]):
        salida["ultimo_latido"] = ahora

    escribir_estado(salida)
    return 2 if fallo else 0


if __name__ == "__main__":
    sys.exit(main())
