#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  PNP  ·  Motor de consulta de citas (Lunas Oscurecidas)
================================================================================

  Habla con el sistema de la PNP por HTTP directo, sin navegador.

  El sitio es ASP.NET WebForms: cada accion es un POST que reenvia los campos
  ocultos (__VIEWSTATE, __EVENTVALIDATION) mas el control que se "pulsa". El
  recorrido completo es:

      1. GET  Solicitud_Menu.aspx      -> campos ocultos iniciales
      2. POST login                    -> Seguimiento.aspx
      3. POST btnAccion de la grilla   -> ficha del expediente
      4. POST btnCita                  -> aparece el formulario de citas
      5. POST cbosede                  -> se rellenan las fechas con cupo
      6. POST cboFecha                 -> se rellenan las horas de esa fecha

  Una consulta completa tarda menos de un segundo. La version con navegador
  tardaba cerca de cien.

  Este modulo solo consulta: no reserva nada. La reserva exige captcha y la
  hace siempre la persona.
================================================================================
"""

from __future__ import annotations

import html as _html
import re

import requests

BASE = "https://sistemas.policia.gob.pe/lunasoscurecidas/"
URL_LOGIN = BASE + "Solicitud_Menu.aspx"
URL_SEG = BASE + "Seguimiento.aspx"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# Prefijo de los controles del formulario de citas (es un user control anidado).
P = "ctl00$MainContent$idUcitas$"

ID_SEDE = "MainContent_idUcitas_cbosede"
ID_FECHA = "MainContent_idUcitas_cboFecha"
ID_HORA = "MainContent_idUcitas_cboHora"
ID_CUPOS = "MainContent_idUcitas_lblcupos"

# Textos que ASP.NET usa como relleno y que no son cupos reales.
RE_VACIO = re.compile(r"sin\s*cupos|seleccione|no\s*hay|^-+$", re.IGNORECASE)
VALORES_VACIOS = {"", "0", "00", "-1"}

# Una fecha real siempre lleva numeros ("15/09/2026", "15 setiembre 2026").
# Exigirlos descarta cualquier relleno de texto sin arriesgar perder un cupo.
RE_TIENE_FECHA = re.compile(r"\d{1,2}\D{0,12}\d{2,4}")

TIMEOUT = 30


class ErrorPNP(Exception):
    """Fallo al consultar el sistema de la PNP."""


class CredencialesInvalidas(ErrorPNP):
    """El sitio rechazo el documento o la clave."""


# --------------------------------------------------------------------------- #

def _ocultos(pagina: str) -> dict:
    """Campos __VIEWSTATE y compania, que hay que devolver en cada POST."""
    return {m.group(1): _html.unescape(m.group(2)) for m in re.finditer(
        r'<input[^>]*type="hidden"[^>]*name="(__[A-Z]+)"[^>]*value="([^"]*)"',
        pagina, re.IGNORECASE)}


def _opciones(pagina: str, id_select: str, exigir_fecha: bool = False) -> list[dict]:
    """Opciones de un <select>, ya filtradas: solo las que son cupos reales."""
    bloque = re.search(rf'<select[^>]*id="{id_select}".*?</select>',
                       pagina, re.S | re.IGNORECASE)
    if not bloque:
        return []
    crudas = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>',
                        bloque.group(0), re.S)
    reales = []
    for valor, texto in crudas:
        valor = _html.unescape(valor).strip()
        texto = _html.unescape(re.sub(r"<[^>]+>", "", texto)).strip()
        if valor in VALORES_VACIOS or not texto or RE_VACIO.search(texto):
            continue
        if exigir_fecha and not RE_TIENE_FECHA.search(texto):
            continue
        reales.append({"value": valor, "text": texto})
    return reales


def _etiqueta(pagina: str, id_lbl: str) -> str:
    m = re.search(rf'id="{id_lbl}"[^>]*>(.*?)</span>', pagina, re.S)
    return _html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def _objetivo_grilla(pagina: str) -> str:
    """Nombre del control del boton 'ver' de la primera fila del expediente.

    Se busca en el HTML en lugar de fijarlo a mano: el indice de fila (ctl02)
    cambia si la PNP altera la cabecera de la tabla.
    """
    m = re.search(r"__doPostBack\(&#39;([^&]*gvProgramacion[^&]*btnAccion)&#39;", pagina)
    if not m:
        m = re.search(r"__doPostBack\('([^']*gvProgramacion[^']*btnAccion)'", pagina)
    if not m:
        raise ErrorPNP("No encuentro tu expediente en el sistema. "
                       "Comprueba que tu tramite siga vigente.")
    return _html.unescape(m.group(1))


# --------------------------------------------------------------------------- #

class SesionPNP:
    """Una consulta completa al sistema de citas."""

    def __init__(self, dni: str, clave: str, tipo_doc: str = "1", sede: str = "1"):
        self.dni = dni.strip()
        self.clave = clave.strip()
        self.tipo_doc = (tipo_doc or "1").strip()
        self.sede = (sede or "1").strip()
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA,
                               "Accept-Language": "es-PE,es;q=0.9"})
        self.evidencia = ""        # HTML de la ultima consulta
        self.etiqueta_cupos = ""   # lo que el sitio dice en su cartel de cupos
        self._form = ""            # ultima pagina con el formulario de citas
        self.reconexiones = 0      # cuantas veces hubo que volver a entrar

    def _post(self, url: str, datos: dict) -> str:
        try:
            r = self.s.post(url, data=datos, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            raise ErrorPNP(f"No pude conectar con el sistema de la PNP: {e}") from e
        return r.text

    def _entrar(self) -> str:
        try:
            r = self.s.get(URL_LOGIN, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            raise ErrorPNP(f"No pude abrir la pagina de la PNP: {e}") from e

        datos = _ocultos(r.text)
        datos.update({"DdlDocumento": self.tipo_doc,
                      "TxtCIP": self.dni,
                      "TxtClave": self.clave,
                      "BtnContinuar": "Continuar"})
        pagina = self._post(URL_LOGIN, datos)

        aviso = _etiqueta(pagina, "LblMensaje")
        if aviso:
            raise CredencialesInvalidas(aviso)
        if 'name="TxtClave"' in pagina:
            raise CredencialesInvalidas(
                "El sistema no acepto tu documento o tu clave.")
        return pagina

    def _abrir_formulario(self, pagina: str) -> str:
        datos = _ocultos(pagina)
        datos["__EVENTTARGET"] = _objetivo_grilla(pagina)
        datos["__EVENTARGUMENT"] = ""
        pagina = self._post(URL_SEG, datos)

        datos = _ocultos(pagina)
        datos["__EVENTTARGET"] = ""
        datos["__EVENTARGUMENT"] = ""
        datos["ctl00$MainContent$btnCita"] = "Reservar Cita"
        pagina = self._post(URL_SEG, datos)

        if ID_SEDE not in pagina:
            raise ErrorPNP("El sistema no mostro el formulario de citas.")
        return pagina

    def _elegir_sede(self, pagina: str) -> str:
        datos = _ocultos(pagina)
        datos["__EVENTTARGET"] = P + "cbosede"
        datos["__EVENTARGUMENT"] = ""
        datos[P + "cbosede"] = self.sede
        return self._post(URL_SEG, datos)

    def _horas_de(self, pagina: str, valor_fecha: str) -> tuple[list[str], str]:
        datos = _ocultos(pagina)
        datos["__EVENTTARGET"] = P + "cboFecha"
        datos["__EVENTARGUMENT"] = ""
        datos[P + "cbosede"] = self.sede
        datos[P + "cboFecha"] = valor_fecha
        detalle = self._post(URL_SEG, datos)
        return ([h["text"] for h in _opciones(detalle, ID_HORA)],
                _etiqueta(detalle, ID_CUPOS))

    def _consultar_formulario(self) -> str:
        """Devuelve la pagina del formulario con las fechas ya cargadas.

        Reutiliza la sesion abierta: basta reenviar el postback de la sede
        sobre la ultima pagina, una sola peticion en lugar de las cinco que
        cuesta entrar de cero. Solo si el sitio ha cerrado la sesion (deja de
        devolver el formulario) se vuelve a hacer el recorrido completo.
        """
        if self._form:
            try:
                pagina = self._elegir_sede(self._form)
                if ID_FECHA in pagina:
                    self._form = pagina
                    return pagina
            except ErrorPNP:
                pass  # sesion caida; se reintenta entrando de nuevo
            self.reconexiones += 1

        self._form = self._abrir_formulario(self._entrar())
        pagina = self._elegir_sede(self._form)
        self._form = pagina
        return pagina

    def consultar(self) -> list[dict]:
        """Devuelve [{fecha, horas, cupos}] con las fechas que tienen cupo.

        Guarda ademas la ultima pagina en self.evidencia: si algun dia avisa de
        un cupo que no existe, ahi queda el HTML exacto para comprobarlo.
        """
        pagina = self._consultar_formulario()
        etiqueta = _etiqueta(pagina, ID_CUPOS)
        self.evidencia = pagina
        self.etiqueta_cupos = etiqueta

        salida = []
        for fecha in _opciones(pagina, ID_FECHA, exigir_fecha=True):
            item = {"fecha": fecha["text"], "horas": [], "cupos": etiqueta}
            try:
                item["horas"], detalle = self._horas_de(pagina, fecha["value"])
                if detalle:
                    item["cupos"] = detalle
            except ErrorPNP:
                pass  # sin el detalle de horas el aviso sigue siendo util
            salida.append(item)
        return salida


def consultar_cupos(dni: str, clave: str, tipo_doc: str = "1",
                    sede: str = "1") -> list[dict]:
    """Atajo: una consulta completa, sesion nueva."""
    return SesionPNP(dni, clave, tipo_doc, sede).consultar()
