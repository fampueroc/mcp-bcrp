"""grafico.png: aciertos por modo (base y sin «null») y la tasa real que calcula tasa_real."""
import asyncio

import matplotlib.pyplot as plt
import pandas as pd
from fastmcp import Client

from server import mcp


async def _tasa_real():
    async with Client(mcp) as c:
        return (await c.call_tool("tasa_real", {"desde": "2021-01", "hasta": "2026-09"})).data


corridas = {"base": pd.read_csv("resultados_base.csv"), "sin null": pd.read_csv("resultados_sin_null.csv")}
pct = pd.DataFrame({k: r.groupby("modo").resultado.apply(lambda s: 100 * (s == "acierta").mean())
                    for k, r in corridas.items()})
tr = pd.DataFrame(asyncio.run(_tasa_real())["meses"])

fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.5), gridspec_kw={"width_ratios": [1, 2]})
pct.plot.bar(ax=a, rot=0, color=["#4C72B0", "#A0B4D8"])
a.set(title="Aciertos por modo (10 preguntas, Haiku)", ylabel="% de aciertos", xlabel="", ylim=(0, 110))
for c in a.containers:
    a.bar_label(c, fmt="%.0f%%")
x = pd.PeriodIndex(tr.periodo, freq="M").to_timestamp()
b.plot(x, tr.referencia, label="Tasa de referencia (PD04722MM)")
b.plot(x, tr.inflacion, label="Inflación 12 meses (PN01273PM)")
b.plot(x, tr.tasa_real, label="Tasa real", color="black", lw=2)
b.axhline(0, color="gray", lw=0.8)
b.axhspan(1.5, 2.5, color="gray", alpha=0.15, label="Zona neutral (2 % ± 0.5)")
b.set(title="Postura monetaria del BCRP con tasa_real, 2021-2026", ylabel="%")
b.legend(fontsize=8)
fig.text(0.99, 0.01, "Fuente: BCRP, API de series estadísticas", ha="right", fontsize=8, color="gray")
fig.tight_layout()
fig.savefig("grafico.png", dpi=150)
print(pct)
