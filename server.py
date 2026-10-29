"""Servidor MCP del BCRP. Empiecen aquí: buscar_series ya funciona; completen los TODO hasta que pasen las pruebas.

    uv run pytest                                           # el contrato: las 8 pruebas deben pasar
    uv run server.py                                        # el servidor, por stdio
    claude mcp add --scope project bcrp -- uv run server.py # conectarlo a Claude Code

Las cuentas las hace Python, no el modelo: así cada cifra sale de una llamada que se puede repetir.
"""
import re
import time
import unicodedata
from functools import cache
from pathlib import Path

import httpx
import pandas as pd
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

AQUI = Path(__file__).parent
CATALOGO = AQUI / "datos" / "catalogo_bcrp.csv"
URL_CATALOGO = "https://estadisticas.bcrp.gob.pe/estadisticas/series/metadata"
API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
SOLO_LECTURA = {"readOnlyHint": True, "openWorldHint": True}

mcp = FastMCP("bcrp", instructions=(
    "Series oficiales del Banco Central de Reserva del Perú (BCRP). Primero busca el código con buscar_series; "
    "luego usa resumen para variaciones, promedios y extremos, y serie para los datos. No calcules a mano: "
    "cita siempre el código de la serie y el periodo."))


def _sin_tildes(s):
    return unicodedata.normalize("NFD", str(s).lower()).encode("ascii", "ignore").decode()


@cache
def catalogo():
    """El catálogo oficial: 17 mil series en unos 7 MB. Se baja una vez y queda en datos/."""
    if not CATALOGO.exists():
        CATALOGO.parent.mkdir(exist_ok=True)
        r = httpx.get(URL_CATALOGO, timeout=120)
        r.raise_for_status()
        CATALOGO.write_text(r.content.decode("latin-1"), encoding="utf-8")
    df = pd.read_csv(CATALOGO, sep=";", dtype=str).fillna("")
    df = df.rename(columns={"Código de serie": "codigo", "Categoría de serie": "categoria", "Grupo de serie": "grupo",
                            "Nombre de serie": "nombre", "Frecuencia": "frecuencia",
                            "Fecha de actualización": "actualizada", "Fecha de inicio": "inicio"})
    df["texto"] = (df.categoria + " " + df.grupo + " " + df.nombre).map(_sin_tildes)
    return df


def _ficha(codigo):
    fila = catalogo().query("codigo == @codigo")
    if fila.empty:
        raise ToolError(f"No existe el código de serie {codigo!r}. Búsquenlo con buscar_series.")
    f = fila.iloc[0]
    return {"codigo": f.codigo, "nombre": f"{f.grupo} - {f.nombre}", "categoria": f.categoria,
            "frecuencia": f.frecuencia, "inicio": f.inicio, "actualizada": f.actualizada}


@mcp.tool(annotations=SOLO_LECTURA)
def buscar_series(texto: str, frecuencia: str | None = None, limite: int = 10) -> list[dict]:
    """Busca series del BCRP por palabras: todas deben aparecer en la categoría, el grupo o el nombre.

    Ejemplos: "ipc 12 meses", "tipo de cambio interbancario venta", "reservas internacionales netas",
    "tasa de referencia", "cobre precio". frecuencia: "Diaria", "Mensual", "Trimestral" o "Anual".
    Devuelve el código, el nombre completo, la frecuencia y desde cuándo hay datos. Si no hay resultados,
    prueben con menos palabras.
    """
    df = catalogo()
    m = pd.Series(True, index=df.index)
    for palabra in _sin_tildes(texto).split():
        m &= df.texto.str.contains(re.escape(palabra))
    if frecuencia:
        m &= df.frecuencia.str.lower() == frecuencia.lower()
    # primero las series vigentes y, entre ellas, las de nombre más corto (las más generales)
    sel = df[m]
    orden = sel.assign(vieja=sel.actualizada < "2025", largo=(sel.grupo + sel.nombre).str.len())
    return [_ficha(c) for c in orden.sort_values(["vieja", "largo"]).head(limite).codigo]


MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
         "jul": 7, "ago": 8, "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12}


def _fecha_api(fecha, frecuencia, fin):
    """Pasa "2025-01", "2025-01-15", "2025-T1" o "2025" al formato que pide la API según la frecuencia."""
    partes = str(fecha).replace("T", "").split("-")
    anio = partes[0]
    if frecuencia == "Anual":
        return anio
    if frecuencia == "Diaria":
        if len(partes) == 3:
            return str(fecha)
        mes = partes[1] if len(partes) > 1 else ("12" if fin else "01")
        dia = str(pd.Period(f"{anio}-{mes}", "M").days_in_month) if fin else "01"
        return f"{anio}-{mes}-{dia}"
    tope = "4" if frecuencia == "Trimestral" else "12"
    return f"{anio}-{int(partes[1]) if len(partes) > 1 else (tope if fin else 1)}"


def _periodo(nombre, frecuencia):
    """Pasa "Ene.2025", "01.Oct.26", "T1.25" o "2025" a "2025-01", "2026-10-01", "2025-T1" o "2025"."""
    if frecuencia == "Anual":
        return nombre
    if frecuencia == "Trimestral":
        t, anio = nombre.split(".")
        return f"20{anio[-2:]}-{t}"
    if frecuencia == "Diaria":
        dia, mes, anio = nombre.split(".")
        return f"20{anio[-2:]}-{MESES[mes.lower()[:3]]:02d}-{int(dia):02d}"
    mes, anio = nombre.split(".")
    return f"{anio}-{MESES[mes.lower()[:3]]:02d}"


@cache
def _descargar(url):
    """Pide la URL a la API; si responde HTML (demasiados pedidos seguidos), espera y reintenta. Queda en caché."""
    for intento in range(4):
        try:
            r = httpx.get(url, timeout=30)
            return tuple(r.json()["periods"])
        except (ValueError, KeyError, httpx.HTTPError):
            time.sleep(2 * (intento + 1))
    raise ToolError(f"El BCRP no respondió con datos para {url}. Esperen unos segundos y reintenten.")


def _serie(codigo, desde, hasta):
    ficha = _ficha(codigo)
    frec = ficha["frecuencia"]
    url = f"{API}/{codigo}/json/{_fecha_api(desde, frec, False)}/{_fecha_api(hasta, frec, True)}"
    datos = [{"periodo": _periodo(p["name"], frec), "valor": float(p["values"][0])}
             for p in _descargar(url) if p["values"][0] not in ("n.d.", "")]
    if not datos:
        raise ToolError(f"La serie {codigo} no tiene datos entre {desde} y {hasta}. Hay datos desde {ficha['inicio']}.")
    return {"codigo": codigo, "nombre": ficha["nombre"], "frecuencia": frec, "datos": datos, "fuente": url}


@mcp.tool(annotations=SOLO_LECTURA)
def serie(codigo: str, desde: str, hasta: str) -> dict:
    """Datos de una serie del BCRP entre dos fechas, ambas incluidas, con la URL de la fuente.

    Fechas: "2025-01" (mensual), "2026-10-01" (diaria), "2025-T1" (trimestral), "2025" (anual).
    Ejemplo: serie("PN01271PM", "2025-01", "2025-12"). Si no saben el código, usen antes buscar_series.
    Para variaciones, promedios o extremos usen resumen en vez de calcular a mano.
    """
    return _serie(codigo, desde, hasta)


@mcp.tool(annotations=SOLO_LECTURA)
def resumen(codigo: str, desde: str, hasta: str) -> dict:
    """Resumen de una serie del BCRP entre dos fechas: primero, último, cambio, variación %, promedio,
    máximo y mínimo (con su periodo), y la URL de la fuente.

    Úsenla para cualquier pregunta de «cuánto subió», «cuál fue el máximo» o «el valor en tal mes», en vez de
    calcular a mano. Mismas fechas que serie. Ejemplo: resumen("PN01273PM", "2025-12", "2026-09").
    """
    s = _serie(codigo, desde, hasta)
    df = pd.DataFrame(s["datos"])
    primero, ultimo = s["datos"][0], s["datos"][-1]
    cambio = ultimo["valor"] - primero["valor"]
    return {"codigo": codigo, "nombre": s["nombre"], "frecuencia": s["frecuencia"], "n": len(df),
            "primero": primero, "ultimo": ultimo, "cambio": round(cambio, 4),
            "variacion_pct": round(100 * cambio / primero["valor"], 2) if primero["valor"] else None,
            "promedio": round(df.valor.mean(), 4),
            "maximo": df.loc[df.valor.idxmax()].to_dict(), "minimo": df.loc[df.valor.idxmin()].to_dict(),
            "fuente": s["fuente"]}

REFERENCIA, INFLACION = "PD04722MM", "PN01273PM"   # tasa de referencia y var% 12 meses del IPC de Lima


@mcp.tool(annotations=SOLO_LECTURA)
def tasa_real(desde: str, hasta: str, neutral: float = 2.0) -> dict:
    """Tasa de interés real del BCRP mes a mes y la postura de la política monetaria: restrictiva, neutral o expansiva.

    Úsenla para preguntas como «¿la política del BCRP fue restrictiva en 2023?», «¿cuándo la tasa real fue
    negativa?» o «¿cuál es la tasa real hoy?». Cruza la tasa de referencia (PD04722MM) con la inflación a
    12 meses de Lima (PN01273PM): tasa real = referencia − inflación (ex post). La postura compara la tasa real
    con una tasa neutral (por defecto 2 %): más de 0.5 puntos por encima es restrictiva, más de 0.5 por debajo
    es expansiva. Fechas mensuales: tasa_real("2021-01", "2026-09").
    """
    ref, inf = _serie(REFERENCIA, desde, hasta), _serie(INFLACION, desde, hasta)
    df = pd.DataFrame(ref["datos"]).merge(pd.DataFrame(inf["datos"]), on="periodo", suffixes=("_ref", "_inf"))
    if df.empty:
        raise ToolError(f"No hay meses con tasa de referencia e inflación a la vez entre {desde} y {hasta}.")
    df = df.rename(columns={"valor_ref": "referencia", "valor_inf": "inflacion"})
    df["tasa_real"] = (df.referencia - df.inflacion).round(2)
    df["postura"] = pd.cut(df.tasa_real - neutral, [-float("inf"), -0.5, 0.5, float("inf")],
                           labels=["expansiva", "neutral", "restrictiva"]).astype(str)
    df["inflacion"] = df.inflacion.round(2)
    # rachas: tramos seguidos con la misma postura
    tramo = (df.postura != df.postura.shift()).cumsum()
    rachas = [{"postura": g.postura.iloc[0], "desde": g.periodo.iloc[0], "hasta": g.periodo.iloc[-1], "meses": len(g)}
              for _, g in df.groupby(tramo)]
    return {"desde": df.periodo.iloc[0], "hasta": df.periodo.iloc[-1], "neutral": neutral,
            "ultimo": df.iloc[-1].to_dict(),
            "meses_por_postura": df.postura.value_counts().to_dict(),
            "meses_con_tasa_real_negativa": int((df.tasa_real < 0).sum()),
            "tasa_real_minima": df.loc[df.tasa_real.idxmin(), ["periodo", "tasa_real"]].to_dict(),
            "tasa_real_maxima": df.loc[df.tasa_real.idxmax(), ["periodo", "tasa_real"]].to_dict(),
            "rachas": rachas, "meses": df.to_dict("records"),
            "fuentes": [ref["fuente"], inf["fuente"]]}


@mcp.resource("bcrp://serie/{codigo}")
def ficha(codigo: str) -> dict:
    """Ficha de una serie del BCRP: nombre, categoría, frecuencia, desde cuándo hay datos y última actualización."""
    return _ficha(codigo)


@mcp.prompt
def postura_monetaria(desde: str, hasta: str) -> str:
    """Informe de la postura monetaria del BCRP en un periodo, con la tasa real y cifras verificables."""
    return (f"Usa la herramienta tasa_real del servidor bcrp entre {desde} y {hasta} y escribe un informe breve en "
            "español: (1) la tasa real y la postura del último mes, (2) los tramos restrictivos, neutrales y "
            "expansivos con sus fechas, (3) los meses con tasa real negativa y (4) la tasa real mínima y máxima. "
            "No calcules a mano: cada cifra debe salir de la herramienta y citar el código de la serie "
            "(PD04722MM o PN01273PM) y el periodo. Termina con las URLs de las fuentes.")


@mcp.prompt
def informe(tema: str) -> str:
    """Informe de cinco viñetas sobre un tema con series del BCRP, cada cifra con su código y periodo."""
    return (f"Escribe un informe de cinco viñetas sobre «{tema}» en el Perú con datos del BCRP. Busca las series con "
            "buscar_series y usa resumen o serie para las cifras; no calcules a mano. Cada viñeta debe citar el "
            "código de la serie y el periodo, y al final lista las URLs de las fuentes.")


if __name__ == "__main__":
    mcp.run()
