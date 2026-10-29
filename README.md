# MCP del BCRP · ¿La política monetaria fue restrictiva o expansiva?

Servidor MCP construido con FastMCP 4 sobre las 17,167 series del Banco Central de Reserva del Perú, conectado a Claude
Code. Además de buscar series y resumirlas, trae una herramienta propia, **`tasa_real`**: resta la inflación a 12 meses
de Lima (PN01273PM) a la tasa de referencia (PD04722MM) y aproxima, mes a mes, si la postura monetaria fue
relativamente restrictiva, neutral o expansiva, citando la URL de cada dato.

Proyecto de la sesión 04 (MCP en Claude Code) del curso Data Science con Python.

## Resultado

Con las mismas 10 preguntas y el modelo Haiku, Claude acertó **0 de 10 de memoria** y **10 de 10 con este MCP**. La
única cifra que dio de memoria estaba equivocada: 6.75 % para la tasa de referencia de mayo de 2024, cuando la oficial
es 5.75 %.

![Aciertos por modo y tasa real del BCRP](grafico.png)

👉 **El análisis completo está en [`informe.md`](informe.md).**

## Qué hace el servidor

| Primitiva | Nombre | Para qué |
|---|---|---|
| Herramienta | `buscar_series` | Encuentra el código de una serie por palabras |
| Herramienta | `serie` | Datos de una serie entre dos fechas, con la URL de la fuente |
| Herramienta | `resumen` | Primero, último, variación, promedio, máximo y mínimo |
| Herramienta (propia) | `tasa_real` | Tasa real y postura monetaria mes a mes, con rachas y extremos |
| Recurso | `bcrp://serie/{codigo}` | Ficha de una serie, para adjuntar con `@` |
| Prompts | `postura_monetaria`, `informe` | Informes con cada cifra citada, con `/` |

## Cómo repetirlo

```bash
uv run pytest -q                                   # 8 passed
claude                                             # aceptar los servidores bcrp y fetch de .mcp.json
uv run evaluar.py --paralelo 2                     # memoria contra MCP → resultados.csv
uv run evaluar.py --paralelo 2 --sin-null --salida resultados_sin_null.csv   # experimento extra
uv run python grafico.py                           # grafico.png
```

En Claude Code: *«¿La política monetaria del BCRP fue restrictiva o expansiva en 2024?»*,
`@bcrp:bcrp://serie/PD04722MM` o `/mcp__bcrp__postura_monetaria 2021-01 2026-09`.

## Archivos

| Grupo | Archivos |
|---|---|
| Lo que se lee | `informe.md`, `grafico.png`, `capturas/` (cifras comprobadas en la web del BCRP) |
| El servidor | `server.py`, `.mcp.json` |
| Las pruebas | `test_server.py` (el contrato del curso, sin cambios) |
| La evaluación | `preguntas.csv`, `evaluar.py`, `resultados.csv`, `resultados_base.csv`, `resultados_sin_null.csv` |
| Configuración | `pyproject.toml`, `uv.lock`, `grafico.py` |

La carpeta `datos/` no está en el repo: el catálogo del BCRP (unos 7 MB) se descarga solo la primera vez.
