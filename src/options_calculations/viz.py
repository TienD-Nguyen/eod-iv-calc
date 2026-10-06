"""Interactive vol viewers, self-contained HTML (no server needed), multi-ticker.

viz.html:    3D gridded surface (log-moneyness x DTE); a ticker dropdown
             (restyle: visibility) composes with the date slider (animate:
             data) because the two controls touch disjoint trace attributes.
smiles.html: one Plotly figure per ticker, each with its own expiry legend
             (click to toggle, double-click to isolate) and date slider; a
             plain HTML <select> swaps which ticker figure is shown.

Scans only the LATEST calculation per ticker under data/<ticker>/<asof>/
(older run dirs are pruned by the pipeline). Plotly is imported lazily so
importing this module stays cheap for the calc path.

Run: python viz.py [out_dir]   (default: data/viz/)
"""
import csv
import math
import sys
from pathlib import Path

import numpy as np

LOCAL_DIR = Path(__file__).parent.resolve()
DATA_DIR = LOCAL_DIR / "../../data"
VIZ_DIR = DATA_DIR / "viz"


def _slider(dates: list[str]) -> list[dict]:
    return [{
        "active": 0, "currentvalue": {"prefix": "Date: "},
        "steps": [{"label": d, "method": "animate",
                   "args": [[d], {"frame": {"duration": 0}, "mode": "immediate"}]}
                  for d in dates],
    }]


def _ticker_dropdown(tickers: list[str], n_traces_of) -> list[dict]:
    """One button per ticker; restyles visibility over trace groups."""
    buttons = []
    for t in tickers:
        visible = [tt == t for tt, _ in n_traces_of]
        buttons.append({"label": t, "method": "restyle", "args": [{"visible": visible}]})
    return [{"buttons": buttons, "direction": "down", "showactive": True,
             "x": 0.0, "y": 1.15, "xanchor": "left", "yanchor": "top"}]


def _latest_files(root: Path, name: str) -> list[Path]:
    """The latest asof dir's file `name`, one per ticker (ISO dates sort as strings)."""
    latest: dict[str, tuple[str, Path]] = {}
    for f in root.glob(f"*/[0-9]*/{name}"):
        ticker, asof = f.parent.parent.name, f.parent.name
        if asof > latest.get(ticker, ("",))[0]:
            latest[ticker] = (asof, f)
    return [f for _, f in latest.values()]


def load_surfaces(root: Path) -> dict[str, dict[str, tuple]]:
    """ticker -> date -> (k, dte, iv%) for the latest surface.csv per ticker."""
    out: dict[str, dict] = {}
    for f in _latest_files(root, "surface.csv"):
        rows = list(csv.reader(open(f)))
        k = np.array([float(x) for x in rows[0][1:]])
        dte, iv = [], []
        for r in rows[1:]:
            dte.append(float(r[0]))
            iv.append([float(x) if x else math.nan for x in r[1:]])
        out.setdefault(f.parent.parent.name, {})[f.parent.name] = (k, np.array(dte), 100 * np.array(iv))
    return out


def load_smiles(root: Path) -> dict[str, dict[str, dict[str, tuple]]]:
    """ticker -> date -> expiry -> (strikes, crr_iv%, dte), latest smile.csv per ticker."""
    out: dict[str, dict] = {}
    for f in _latest_files(root, "smile.csv"):
        day: dict[str, list] = {}
        for r in csv.DictReader(open(f)):
            if r["crr_iv"]:
                day.setdefault(r["expiry"], []).append(
                    (float(r["strike"]), 100 * float(r["crr_iv"]), int(r["dte"])))
        out.setdefault(f.parent.parent.name, {})[f.parent.name] = {
            e: (np.array([v[0] for v in sorted(v)]), np.array([v[1] for v in sorted(v)]),
                sorted(v)[0][2])
            for e, v in day.items()}
    return out


def build_surface_figure(surfaces: dict):
    import plotly.graph_objects as go
    tickers = sorted(surfaces)
    dates = sorted({d for t in surfaces.values() for d in t})
    first = tickers[0]

    def surface_for(t: str, d: str) -> go.Surface:
        hover = ("ln(K/F): %{x:.3f}<br>DTE: %{y}<br>IV: %{z:.2f}%"
                 "<extra>%{fullData.name}</extra>")
        if d in surfaces[t]:
            k, dte, iv = surfaces[t][d]
            return go.Surface(x=k, y=dte, z=iv, name=t, showscale=False,
                              hovertemplate=hover)
        return go.Surface(x=[], y=[], z=[[]], name=t, showscale=False,
                          hovertemplate=hover)

    data = []
    for t in tickers:
        tr = surface_for(t, next(iter(surfaces[t])))
        tr.visible = (t == first)
        data.append(tr)
    fig = go.Figure(
        data=data,
        frames=[go.Frame(name=d, data=[surface_for(t, d) for t in tickers])
                for d in dates],
    )
    fig.update_layout(
        title="Implied-vol surface (gridded)",
        scene=dict(xaxis_title="log-moneyness ln(K/F)", yaxis_title="DTE",
                   zaxis_title="IV %"),
        sliders=_slider(dates),
        updatemenus=_ticker_dropdown(tickers, [(t, None) for t in tickers]),
    )
    return fig


def build_smile_figure(ticker: str, days: dict):
    """One figure per ticker: one trace per expiry, toggled by legend clicks
    (double-click isolates); date slider for the asof day."""
    import plotly.graph_objects as go
    dates = sorted(days)
    expiries = sorted({e for day in days.values() for e in day})

    def traces_for(day: str) -> list[go.Scatter]:
        traces = []
        for e in expiries:
            if e in days[day]:
                strikes, ivs, dte = days[day][e]
            else:
                strikes, ivs, dte = [], [], 0
            traces.append(go.Scatter(
                x=strikes, y=ivs, customdata=np.full(len(strikes), dte),
                mode="lines+markers", name=e,
                hovertemplate=("Expiry: %{fullData.name} (DTE: %{customdata})<br>"
                               "Strike: %{x:.2f}<br>IV %{y:.2f}%<extra></extra>")))
        return traces

    fig = go.Figure(
        data=traces_for(dates[0]),
        frames=[go.Frame(name=d, data=traces_for(d)) for d in dates],
    )
    fig.update_layout(
        title=f"{ticker} volatility smile (native quotes)",
        xaxis_title="Strike", yaxis_title="IV %",
        legend_title="Expiry",
        sliders=_slider(dates),
    )
    return fig


def write_smiles_html(figs: dict, out: Path) -> None:
    """One HTML, one figure per ticker, swapped by a plain <select>."""
    import plotly.io as pio
    tickers = sorted(figs)
    options = "".join(f'<option value="{t}">{t}</option>' for t in tickers)
    divs = []
    for i, t in enumerate(tickers):
        style = "" if i == 0 else ' style="display:none"'
        divs.append(f'<div id="fig_{t}"{style}>'
                    + pio.to_html(figs[t], full_html=False, include_plotlyjs=(i == 0),
                                  div_id=f"plot_{t}")
                    + "</div>")
    out.write_text(
        "<html><head><meta charset='utf-8'></head><body>"
        f"<label>Ticker: <select onchange=\"for (const d of document.querySelectorAll('div[id^=fig_]')) "
        f"d.style.display = d.id === 'fig_' + this.value ? '' : 'none'; "
        f"Plotly.Plots.resize(document.getElementById('plot_' + this.value))\">{options}</select></label>"
        + "".join(divs) + "</body></html>"
    )


def regenerate(data_dir: Path = DATA_DIR, out_dir: Path = VIZ_DIR) -> None:
    """Rebuild both viewers from the latest calculation per ticker."""
    out_dir.mkdir(parents=True, exist_ok=True)
    surfaces = load_surfaces(data_dir)
    surf = build_surface_figure(surfaces)
    (out_dir / "viz.html").write_text(surf.to_html())
    smiles = load_smiles(data_dir)
    figs = {t: build_smile_figure(t, days) for t, days in smiles.items()}
    write_smiles_html(figs, out_dir / "smiles.html")
    print(f"{out_dir}/viz.html: {len(surfaces)} ticker(s) | "
          f"smiles.html: {len(figs)} ticker figure(s)")


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else VIZ_DIR
    regenerate(out_dir=out_dir)
    assert (out_dir / "viz.html").exists() and (out_dir / "smiles.html").exists()
    print("OK")
