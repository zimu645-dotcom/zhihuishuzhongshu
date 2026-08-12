"""
智汇中枢 - AI 可视化大屏渲染器

AI 生成 dashboard spec(JSON) → 本模块渲染成自包含 HTML（内嵌 ECharts）。
不固定模板：布局、组件类型、数量、配色全部由 spec 决定。
"""

import os
import json
import html as _html


# ═══════════════════════════════════════
# 主题与色板
# ═══════════════════════════════════════

THEMES = {
    "dark": {
        "bg": "#0d1117", "card": "#161b22", "border": "#21262d",
        "text": "#e6edf3", "muted": "#8b949e", "accent": "#58a6ff",
        "grid": "#30363d", "kpi_bg": "#1a2433",
        "palette": ["#3987e5", "#d95926", "#199e70", "#c98500",
                    "#d55181", "#008300", "#9085e9", "#e66767"],
    },
    "light": {
        "bg": "#f4f6fb", "card": "#ffffff", "border": "#e6e8ef",
        "text": "#1f2328", "muted": "#6e7781", "accent": "#2a78d6",
        "grid": "#d0d7de", "kpi_bg": "#f0f4ff",
        "palette": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                    "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    },
}

# ECharts 图表组件类型
CHART_TYPES = {"bar", "hbar", "line", "area", "pie", "donut", "radar",
               "scatter", "bubble", "heatmap", "gauge", "funnel"}
# 需要 data 对象的图表类型（gauge 用 value/max，不需要）
NEED_DATA_TYPES = CHART_TYPES - {"gauge"}
# 非图表组件类型
HTML_TYPES = {"kpi", "table", "rank", "text", "divider"}
ALL_TYPES = CHART_TYPES | HTML_TYPES

MAX_COMPONENTS = 15
DOWN_SAMPLE_LIMIT = 120
ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"


# ═══════════════════════════════════════
# 基础工具
# ═══════════════════════════════════════

def _escape_html(s):
    return _html.escape(str(s), quote=True)


def _deep_merge(base, override):
    """递归深合并 override 到 base（AI 的 option 覆盖默认值）"""
    if not isinstance(override, dict):
        return
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _downsample(data, limit=DOWN_SAMPLE_LIMIT):
    """超长序列降采样，避免大屏卡顿"""
    if not isinstance(data, list) or len(data) <= limit:
        return data
    step = len(data) / float(limit)
    return [data[int(i * step)] for i in range(limit)]


def _fmt_value(v, vf="auto"):
    """数字格式化：compact/number/percent/currency/auto"""
    if isinstance(v, str):
        return v
    try:
        f = float(v)
    except Exception:
        return str(v)
    if vf == "percent":
        return f"{f:g}%"
    if vf == "currency":
        return f"¥{f:,.0f}"
    if vf == "number":
        return f"{f:,.0f}"
    # auto / compact（中文习惯：万/亿）
    if abs(f) >= 100000000:
        return f"{f / 1e8:.2f}亿"
    if abs(f) >= 10000:
        return f"{f / 1e4:.1f}万"
    if f == int(f):
        return f"{int(f):,}"
    return f"{f:g}"


def _sparkline_svg(values, color, w=200, h=44):
    """迷你趋势 SVG"""
    if not values:
        return ""
    vals = [float(v) for v in values]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = (i / (n - 1)) * w if n > 1 else w / 2
        y = h - 4 - (v - lo) / span * (h - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg class="kpi-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round" '
            f'points="{" ".join(pts)}"/></svg>')


def _auto_layout(comps, cols):
    """对缺 x/y 的组件按自动流排布（瀑布流式）"""
    x, y, row_h = 0, 0, 0
    for c in comps:
        w = min(int(c.get("w", 6)), cols)
        h = int(c.get("h", 4))
        if x + w > cols:
            x, y = 0, y + row_h
            row_h = 0
        c["x"], c["y"] = x, y
        x += w
        row_h = max(row_h, h)


# ═══════════════════════════════════════
# spec 校验
# ═══════════════════════════════════════

def validate_spec(spec):
    """宽松校验并补默认值。返回错误列表（空=通过）；未知类型组件标记 _skipped。"""
    errors = []
    if not isinstance(spec, dict):
        return ["spec 必须是 JSON 对象"]
    spec.setdefault("title", "AI可视化大屏")
    spec.setdefault("theme", "dark")
    comps = spec.get("components")
    if not isinstance(comps, list) or not comps:
        return ["components 不能为空，至少需要一个组件"]
    if len(comps) > MAX_COMPONENTS:
        errors.append(f"组件数量 {len(comps)} 超过上限 {MAX_COMPONENTS}，请精简")
    cols = int((spec.get("page", {}) or {}).get("cols", 24))
    needs_layout = all(("x" not in c or "y" not in c) for c in comps if isinstance(c, dict))
    auto_idx = 0
    for i, c in enumerate(comps):
        if not isinstance(c, dict):
            errors.append(f"组件 {i} 必须是对象")
            continue
        t = c.get("type")
        if t not in ALL_TYPES:
            c["_skipped"] = True  # 未知类型跳过，不报硬错误
            continue
        c.setdefault("title", "")
        c.setdefault("w", 6)
        c.setdefault("h", 4)
        if t in NEED_DATA_TYPES and not isinstance(c.get("data"), dict):
            errors.append(f"组件「{c.get('title', '')}」缺少 data 数据")
            c["_skipped"] = True
    # 布局：缺 x/y 的组件自动排布
    if needs_layout:
        _auto_layout([c for c in comps if isinstance(c, dict) and not c.get("_skipped")], cols)
    return errors


# ═══════════════════════════════════════
# ECharts option 模板
# ═══════════════════════════════════════

def _base_opt(c, T, trigger):
    opt = {
        "color": list(T["palette"]),
        "tooltip": {"trigger": trigger},
    }
    if c.get("title"):
        opt["title"] = {
            "text": c["title"], "left": "center",
            "textStyle": {"color": T["text"], "fontSize": 14, "fontWeight": 600},
        }
    return opt


def _chart_option(ctype, c, T):
    data = c.get("data", {}) or {}
    overrides = c.get("option", {}) or {}

    if ctype in ("bar", "hbar"):
        cats = _downsample(data.get("categories", []))
        series = []
        for s in data.get("series", []):
            sdata = _downsample(s.get("data", []))
            if ctype == "hbar":
                series.append({
                    "name": s.get("name", ""), "type": "bar",
                    "data": sdata, "barWidth": "60%",
                    "itemStyle": {"borderRadius": [0, 4, 4, 0]},
                })
            else:
                series.append({
                    "name": s.get("name", ""), "type": "bar",
                    "data": sdata, "barWidth": "60%",
                    "itemStyle": {"borderRadius": [4, 4, 0, 0]},
                    "stack": "total" if c.get("stack") else None,
                })
        opt = _base_opt(c, T, "axis")
        opt["legend"] = {"top": 30, "textStyle": {"color": T["muted"]}}
        opt["grid"] = {"left": 56, "right": 16, "top": 60, "bottom": 36}
        if ctype == "hbar":
            opt["yAxis"] = {"type": "category", "data": cats,
                            "axisLabel": {"color": T["muted"]},
                            "axisLine": {"lineStyle": {"color": T["grid"]}}}
            opt["xAxis"] = {"type": "value", "axisLabel": {"color": T["muted"]},
                            "splitLine": {"lineStyle": {"color": T["grid"]}}}
        else:
            opt["xAxis"] = {"type": "category", "data": cats,
                            "axisLabel": {"color": T["muted"]},
                            "axisLine": {"lineStyle": {"color": T["grid"]}}}
            opt["yAxis"] = {"type": "value", "axisLabel": {"color": T["muted"]},
                            "splitLine": {"lineStyle": {"color": T["grid"]}}}
        opt["series"] = series

    elif ctype in ("line", "area"):
        cats = _downsample(data.get("categories", []))
        series = []
        for s in data.get("series", []):
            item = {
                "name": s.get("name", ""), "type": "line",
                "data": _downsample(s.get("data", [])),
                "smooth": c.get("smooth", True),
                "symbolSize": 6,
            }
            if ctype == "area":
                item["areaStyle"] = {"opacity": 0.10}
            series.append(item)
        opt = _base_opt(c, T, "axis")
        opt["legend"] = {"top": 30, "textStyle": {"color": T["muted"]}}
        opt["grid"] = {"left": 56, "right": 16, "top": 60, "bottom": 36}
        opt["xAxis"] = {"type": "category", "boundaryGap": False, "data": cats,
                        "axisLabel": {"color": T["muted"]},
                        "axisLine": {"lineStyle": {"color": T["grid"]}}}
        opt["yAxis"] = {"type": "value", "axisLabel": {"color": T["muted"]},
                        "splitLine": {"lineStyle": {"color": T["grid"]}}}
        opt["series"] = series

    elif ctype in ("pie", "donut"):
        items = data.get("items", []) or []
        radius = ["42%", "70%"] if ctype == "donut" else "68%"
        opt = _base_opt(c, T, "item")
        opt["legend"] = {"bottom": 0, "textStyle": {"color": T["muted"]}}
        opt["series"] = [{
            "type": "pie", "radius": radius, "center": ["50%", "52%"],
            "roseType": "area" if c.get("rose") else None,
            "itemStyle": {"borderColor": T["card"], "borderWidth": 2,
                          "borderRadius": 4 if ctype == "donut" else 0},
            "label": {"color": T["text"]},
            "labelLine": {"lineStyle": {"color": T["muted"]}},
            "data": items,
        }]

    elif ctype == "radar":
        indicators = data.get("indicators", []) or []
        series_data = [{"name": s.get("name", ""), "value": s.get("data", []),
                        "areaStyle": {"opacity": 0.12}}
                       for s in data.get("series", [])]
        opt = _base_opt(c, T, "item")
        opt["legend"] = {"bottom": 0, "textStyle": {"color": T["muted"]}}
        opt["radar"] = {
            "indicator": indicators,
            "axisName": {"color": T["text"]},
            "axisLine": {"lineStyle": {"color": T["grid"]}},
            "splitLine": {"lineStyle": {"color": T["grid"]}},
            "splitArea": {"areaStyle": {"color": ["rgba(0,0,0,0.02)"]}},
        }
        opt["series"] = [{"type": "radar", "symbol": "none", "data": series_data}]

    elif ctype in ("scatter", "bubble"):
        points = data.get("points", []) or []
        pdata = [[p.get("x", 0), p.get("y", 0), p.get("size", 10), p.get("name", "")]
                 for p in points]
        opt = _base_opt(c, T, "item")
        opt["grid"] = {"left": 56, "right": 16, "top": 50, "bottom": 36}
        opt["xAxis"] = {"type": "value", "name": data.get("x_axis", ""),
                        "nameTextStyle": {"color": T["muted"]},
                        "axisLabel": {"color": T["muted"]},
                        "splitLine": {"lineStyle": {"color": T["grid"]}}}
        opt["yAxis"] = {"type": "value", "name": data.get("y_axis", ""),
                        "nameTextStyle": {"color": T["muted"]},
                        "axisLabel": {"color": T["muted"]},
                        "splitLine": {"lineStyle": {"color": T["grid"]}}}
        if ctype == "bubble":
            opt["series"] = [{
                "type": "scatter",
                "symbolSize": "function(v){return Math.max(4, v[2]);}",
                "data": pdata,
                "label": {"show": True, "formatter": "function(p){return p.data[3];}",
                          "position": "top", "color": T["muted"], "fontSize": 11},
            }]
        else:
            opt["series"] = [{
                "type": "scatter",
                "symbolSize": 12,
                "data": pdata,
                "label": {"show": True, "formatter": "function(p){return p.data[3];}",
                          "position": "top", "color": T["muted"], "fontSize": 11},
            }]

    elif ctype == "heatmap":
        xcats = data.get("x", []) or []
        ycats = data.get("y", []) or []
        values = data.get("values", []) or []
        if values and isinstance(values[0], list) and len(values[0]) == 3:
            cells = [[int(a), int(b), float(cv)] for a, b, cv in values]
        else:
            cells = []
            for yi, row in enumerate(values):
                for xi, cv in enumerate(row):
                    cells.append([xi, yi, float(cv)])
        maxv = max((cv[2] for cv in cells), default=1)
        opt = _base_opt(c, T, "item")
        opt["grid"] = {"left": 56, "right": 16, "top": 50, "bottom": 44}
        opt["xAxis"] = {"type": "category", "data": xcats, "splitArea": {"show": True},
                        "axisLabel": {"color": T["muted"]},
                        "axisLine": {"lineStyle": {"color": T["grid"]}}}
        opt["yAxis"] = {"type": "category", "data": ycats, "splitArea": {"show": True},
                        "axisLabel": {"color": T["muted"]},
                        "axisLine": {"lineStyle": {"color": T["grid"]}}}
        opt["visualMap"] = {
            "min": 0, "max": maxv or 1, "calculable": True, "orient": "horizontal",
            "left": "center", "bottom": 0,
            "inRange": {"color": [T["card"], T["accent"]]},
        }
        opt["series"] = [{"type": "heatmap", "data": cells,
                          "label": {"show": True, "color": T["text"], "fontSize": 11},
                          "itemStyle": {"borderColor": T["card"], "borderWidth": 1}}]

    elif ctype == "gauge":
        value = c.get("value", 0)
        unit = str(c.get("unit", ""))  # 不在此转义，统一由 data-opt 层 html.escape
        opt = _base_opt(c, T, "item")
        opt["series"] = [{
            "type": "gauge", "startAngle": 210, "endAngle": -30,
            "min": c.get("min", 0), "max": c.get("max", 100),
            "progress": {"show": True, "width": 14, "itemStyle": {"color": T["accent"]}},
            "axisLine": {"lineStyle": {"width": 14, "color": [[1, "rgba(128,128,128,0.18)"]]}},
            "axisTick": {"show": False}, "splitLine": {"show": False},
            "pointer": {"show": True, "length": "60%", "width": 5},
            "axisLabel": {"color": T["muted"], "distance": 22},
            "title": {"show": True, "color": T["muted"], "offsetCenter": [0, "38%"]},
            "detail": {"valueAnimation": True, "color": T["text"], "fontSize": 26,
                       "offsetCenter": [0, "72%"], "formatter": "{value}" + unit},
            "data": [{"value": value, "name": c.get("title", "")}],
        }]

    elif ctype == "funnel":
        items = data.get("items", []) or []
        opt = _base_opt(c, T, "item")
        opt["legend"] = {"bottom": 0, "textStyle": {"color": T["muted"]}}
        opt["series"] = [{
            "type": "funnel", "left": "15%", "top": 34, "bottom": 40, "width": "70%",
            "minSize": "0%", "maxSize": "100%", "sort": "descending", "gap": 2,
            "label": {"show": True, "position": "inside", "color": T["text"]},
            "itemStyle": {"borderColor": T["card"], "borderWidth": 1},
            "data": items,
        }]

    else:
        opt = _base_opt(c, T, "item")

    _deep_merge(opt, overrides)
    return opt


# ═══════════════════════════════════════
# 组件 HTML 渲染
# ═══════════════════════════════════════

def _panel_style(c):
    """网格定位样式"""
    x, y = int(c.get("x", 0)), int(c.get("y", 0))
    w, h = int(c.get("w", 6)), int(c.get("h", 4))
    return (f"grid-column:{x + 1}/span {w}; grid-row:{y + 1}/span {h};"
            f"--panel-h:{max(h * 60, 120)}px;")


def _render_kpi(c, T):
    fmt = _escape_html(_fmt_value(c.get("value", 0), c.get("value_format", "auto")))
    unit = _escape_html(str(c.get("unit", "")))
    title = _escape_html(str(c.get("title", "")))
    icon = _escape_html(str(c.get("icon", "")))
    delta_html = ""
    delta = c.get("delta")
    if delta is not None:
        up = float(delta) >= 0
        good_when_up = c.get("delta_good_when", "up") == "up"
        cls = "good" if up == good_when_up else "bad"
        arrow = "▲" if up else "▼"
        d_label = _escape_html(str(c.get("delta_label", "")))
        delta_html = f'<div class="kpi-delta {cls}">{arrow} {abs(delta):g}{_escape_html(c.get("delta_unit", "%"))} {d_label}</div>'
    spark = _sparkline_svg(c.get("sparkline") or [], T["accent"]) if c.get("sparkline") else ""
    return f'''<div class="panel kpi" style="{_panel_style(c)}">
      <div class="kpi-title">{icon} {title}</div>
      <div class="kpi-value">{fmt}<span class="kpi-unit">{unit}</span></div>
      {delta_html}{spark}
    </div>'''


def _render_table(c, T):
    cols = c.get("columns", []) or []
    rows = (c.get("rows", []) or [])[: int(c.get("max_rows", 50))]
    head = "".join(f"<th>{_escape_html(cl)}</th>" for cl in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{_escape_html(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'''<div class="panel" style="{_panel_style(c)}">
      <div class="panel-title">{_escape_html(str(c.get("title", "")))}</div>
      <div class="table-wrap"><table class="dash-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
    </div>'''


def _render_rank(c, T):
    items = (c.get("items", []) or [])[:20]
    show_idx = c.get("show_index", True)
    unit = _escape_html(str(c.get("unit", "")))
    rows = []
    for i, it in enumerate(items):
        name = _escape_html(str(it.get("name", "")))
        extra = _escape_html(str(it.get("extra", "")))
        val = _escape_html(_fmt_value(it.get("value", 0), c.get("value_format", "auto")))
        idx = f'<span class="rank-idx">{i + 1}</span>' if show_idx else ""
        rows.append(f'<div class="rank-item">{idx}<span class="rank-name">{name}</span>'
                    f'<span class="rank-extra">{extra}</span><span class="rank-val">{val}{unit}</span></div>')
    return f'''<div class="panel" style="{_panel_style(c)}">
      <div class="panel-title">{_escape_html(str(c.get("title", "")))}</div>
      <div class="rank-list">{"".join(rows)}</div></div>'''


def _render_text(c, T):
    fs = int(c.get("font_size", 16))
    color = _escape_html(c.get("color") or T["text"])
    align = c.get("align", "left")
    txt = _escape_html(str(c.get("text", "")))
    return f'''<div class="panel text-panel" style="{_panel_style(c)}">
      <div style="font-size:{fs}px;color:{color};text-align:{align};">{txt}</div></div>'''


def _render_divider(c, T):
    return f'<div class="panel divider" style="{_panel_style(c)}">' \
           f'<hr style="border:none;border-top:1px solid {T["grid"]};margin:0;width:100%;"></div>'


def _render_chart_panel(c, ctype, cid, T, opt):
    title_html = (f'<div class="panel-title">{_escape_html(str(c.get("title", "")))}</div>'
                  if c.get("title") else "")
    opt_json = _escape_html(json.dumps(opt, ensure_ascii=False))
    return f'''<div class="panel" style="{_panel_style(c)}">
      {title_html}
      <div class="chart" id="{cid}" data-opt="{opt_json}"></div>
    </div>'''


def _render_component(c, ctype, cid, T):
    if ctype in ("kpi",):
        return _render_kpi(c, T)
    if ctype == "table":
        return _render_table(c, T)
    if ctype == "rank":
        return _render_rank(c, T)
    if ctype == "text":
        return _render_text(c, T)
    if ctype == "divider":
        return _render_divider(c, T)
    # ECharts 图表
    opt = _chart_option(ctype, c, T)
    return _render_chart_panel(c, ctype, cid, T, opt)


# ═══════════════════════════════════════
# 数据提取（供 AI 理解数据结构）
# ═══════════════════════════════════════

def _norm(v):
    if v is None or (hasattr(v, "__class__") and v.__class__.__name__ == "float" and v != v):
        return ""
    try:
        if v != v:  # NaN
            return ""
    except Exception:
        pass
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else round(float(v), 4)
    return str(v)


def _num(v):
    try:
        f = float(v)
        if f != f:
            return 0
        return int(f) if f.is_integer() else round(f, 2)
    except Exception:
        return 0


def _read_csv_smart(path, max_rows):
    import pandas as pd
    last = None
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            return pd.read_csv(path, nrows=max_rows, encoding=enc)
        except UnicodeDecodeError as e:
            last = e
            continue
        except Exception:
            raise
    raise last


def _summarize_df(df, name, preview_n):
    import pandas as pd
    cols = [str(c) for c in df.columns]
    col_types, num_sum = {}, {}
    head = []
    for row in df.head(preview_n).itertuples(index=False):
        head.append([_norm(v) for v in row])
    for col in df.columns:
        s = df[col]
        cname = str(col)
        if pd.api.types.is_numeric_dtype(s):
            col_types[cname] = "numeric"
            try:
                num_sum[cname] = {"min": _num(s.min()), "max": _num(s.max()),
                                  "mean": round(float(s.mean()), 2),
                                  "sum": _num(s.sum())}
            except Exception:
                pass
        else:
            col_types[cname] = "string"
    top = {}
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            continue
        try:
            vc = df[col].value_counts().head(8)
            top[str(col)] = [[str(k), int(v)] for k, v in vc.items()]
        except Exception:
            pass
    return {
        "sheet_name": name,
        "row_count": int(len(df)),
        "columns": cols,
        "column_types": col_types,
        "head": head,
        "numeric_summary": num_sum,
        "top_categories": top,
    }


def extract_structured_data(path, file_type, max_rows=100, max_preview_rows=20):
    """用 pandas 重读原始文件，产出结构化 JSON。仅支持 xlsx/csv。"""
    if not path or not os.path.exists(path):
        return {"status": "error", "error": "文件不存在"}
    try:
        import pandas as pd
        if file_type == "xlsx":
            xls = pd.ExcelFile(path)
            sheets = []
            for sn in xls.sheet_names[:5]:
                df = pd.read_excel(path, sheet_name=sn, nrows=max_rows)
                sheets.append(_summarize_df(df, sn, max_preview_rows))
            return {"status": "success", "file_type": "xlsx", "sheets": sheets}
        if file_type == "csv":
            df = _read_csv_smart(path, max_rows)
            return {"status": "success", "file_type": "csv",
                    "sheets": [_summarize_df(df, "Sheet1", max_preview_rows)]}
        return {"status": "error", "error": "仅支持 xlsx/csv 生成大屏"}
    except Exception as e:
        return {"status": "error", "error": f"读取失败: {str(e)[:120]}"}


def build_data_preview(structured, max_chars=4000):
    """把结构化数据压成紧凑文本，注入 AI 上下文"""
    if not structured or structured.get("status") != "success":
        return ""
    parts = []
    for s in structured.get("sheets", []):
        L = []
        L.append(f"Sheet: {s['sheet_name']} | {s['row_count']} 行")
        L.append(f"列: {', '.join(s['columns'])}")
        types = " | ".join(f"{k}({v})" for k, v in s["column_types"].items())
        L.append(f"类型: {types}")
        if s["numeric_summary"]:
            ss = " | ".join(
                f"{k}: min={v['min']} max={v['max']} mean={v['mean']} sum={v['sum']}"
                for k, v in s["numeric_summary"].items())
            L.append(f"数值概要: {ss}")
        if s["top_categories"]:
            tc = " | ".join(f"{k}→{v}" for k, v in list(s["top_categories"].items())[:3])
            L.append(f"分类Top: {tc}")
        L.append(f"前{len(s['head'])}行:")
        for row in s["head"]:
            L.append("  " + " | ".join(str(x) for x in row))
        parts.append("\n".join(L))
    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(已截断)"
    return text


# ═══════════════════════════════════════
# ECharts 依赖
# ═══════════════════════════════════════

def ensure_echarts(static_dir=None):
    """本地缓存 echarts.min.js（首次联网下载）。返回 JS 文本；不可用返回 None。"""
    if not static_dir:
        return None
    p = os.path.join(static_dir, "echarts.min.js")
    if os.path.exists(p) and os.path.getsize(p) > 100000:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    try:
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(ECHARTS_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            data = r.read().decode("utf-8")
        if len(data) < 100000:
            return None
        os.makedirs(static_dir, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(data)
        return data
    except Exception:
        return None


def _echarts_block(static_dir):
    js = ensure_echarts(static_dir)
    if js:
        js = js.replace("</script", "<\\/script")
        return f"<script>{js}</script>"
    return (
        f'<script src="{ECHARTS_URL}"></script>'
        '<script>window.addEventListener("DOMContentLoaded",function(){'
        'if(!window.echarts){document.querySelectorAll(".chart").forEach(function(el){'
        'el.innerHTML="<div class=\'chart-error\'>图表库加载失败，请联网后重新生成</div>";});}'
        '});</script>'
    )


# ═══════════════════════════════════════
# HTML 渲染主函数
# ═══════════════════════════════════════

CSS = """
* { box-sizing:border-box; margin:0; padding:0; }
html,body { height:100%; }
body { background:var(--bg); color:var(--text);
  font-family:'Microsoft YaHei','PingFang SC',system-ui,-apple-system,sans-serif; }
.dashboard { display:grid; grid-template-columns:repeat(var(--cols), 1fr);
  gap:var(--gap); padding:var(--padding); grid-auto-rows:var(--row-h); }
.panel { background:var(--card); border:1px solid var(--border); border-radius:12px;
  padding:12px; display:flex; flex-direction:column; min-height:var(--panel-h);
  overflow:hidden; }
.panel-title { font-size:13px; font-weight:600; color:var(--muted);
  margin-bottom:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.chart { flex:1; min-height:0; width:100%; }
.chart-error { color:var(--muted); font-size:13px; display:flex;
  align-items:center; justify-content:center; height:100%; }
/* KPI */
.kpi { justify-content:center; align-items:flex-start; background:var(--kpi-bg); }
.kpi-title { color:var(--muted); font-size:13px; }
.kpi-value { font-size:34px; font-weight:700; margin:6px 0 2px; letter-spacing:-0.5px; }
.kpi-unit { font-size:13px; font-weight:400; color:var(--muted); margin-left:4px; }
.kpi-delta { font-size:12px; margin-top:4px; }
.kpi-delta.good { color:#0ca30c; }
.kpi-delta.bad  { color:#d03b3b; }
.kpi-spark { width:100%; height:40px; margin-top:10px; }
/* 表格 */
.table-wrap { flex:1; overflow:auto; }
.dash-table { width:100%; border-collapse:collapse; font-size:12px; }
.dash-table th { text-align:left; padding:6px 8px; color:var(--muted);
  border-bottom:1px solid var(--grid); font-weight:500; position:sticky; top:0; background:var(--card); }
.dash-table td { padding:6px 8px; border-bottom:1px solid var(--grid); }
/* 排名 */
.rank-list { display:flex; flex-direction:column; gap:6px; overflow-y:auto; }
.rank-item { display:flex; align-items:center; gap:8px; padding:6px 8px;
  border-radius:8px; background:rgba(0,0,0,0.04); font-size:13px; }
.rank-idx { width:20px; height:20px; border-radius:6px; background:var(--accent);
  color:#fff; display:inline-flex; align-items:center; justify-content:center;
  font-size:12px; margin-right:2px; flex-shrink:0; }
.rank-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rank-extra { color:var(--muted); font-size:12px; }
.rank-val { font-weight:600; }
/* 文本 / 分隔线 */
.text-panel { justify-content:center; align-items:center; }
.divider { border:none; background:transparent; padding:0; }
"""

JAVASCRIPT = """
function initAllCharts() {
  document.querySelectorAll('.chart').forEach(function(el) {
    var opt = null;
    try { opt = JSON.parse(el.dataset.opt || 'null'); } catch(e) { opt = null; }
    if (!opt) { el.innerHTML = '<div class="chart-error">图表配置解析失败</div>'; return; }
    if (typeof echarts === 'undefined') {
      el.innerHTML = '<div class="chart-error">图表库未加载</div>'; return;
    }
    try {
      var chart = echarts.init(el);
      chart.setOption(opt);
      window.addEventListener('resize', function() { chart.resize(); });
      setTimeout(function(){ chart.resize(); }, 100);
    } catch(e) {
      el.innerHTML = '<div class="chart-error">图表渲染失败</div>';
    }
  });
}
window.addEventListener('DOMContentLoaded', initAllCharts);
"""


def render_dashboard(spec, output_path, static_dir=None):
    """spec → 自包含 HTML 文件。返回 {"status","path","warnings"} 或 {"status":"error","errors"}。"""
    try:
        errors = validate_spec(spec)
        comps = [c for c in spec.get("components", []) if isinstance(c, dict) and not c.get("_skipped")]
        if not comps:
            return {"status": "error", "errors": errors or ["没有可渲染的组件"]}

        theme = spec.get("theme", "dark")
        if theme not in THEMES:
            theme = "dark"
        T = dict(THEMES[theme])
        if spec.get("palette"):
            pal = [p for p in spec["palette"] if isinstance(p, str)][:8]
            if pal:
                T["palette"] = pal
        if spec.get("background"):
            T["bg"] = spec["background"]
        if spec.get("accent"):
            T["accent"] = spec["accent"]

        page = spec.get("page", {}) or {}
        cols = max(int(page.get("cols", 24)), 4)
        gap = int(page.get("gap", 12))
        padding = int(page.get("padding", 16))
        row_h = int(page.get("row_height", 60))

        max_y = max((int(c.get("y", 0)) + int(c.get("h", 4))) for c in comps)
        body_h = (max_y + 1) * row_h + 40

        panels = []
        for i, c in enumerate(comps):
            ctype = c.get("type")
            panels.append(_render_component(c, ctype, f"c{i}", T))

        title = _escape_html(spec.get("title", "AI可视化大屏"))
        subtitle = _escape_html(str(spec.get("subtitle", "")))

        css_vars = (
            f"--bg:{T['bg']}; --card:{T['card']}; --border:{T['border']}; "
            f"--text:{T['text']}; --muted:{T['muted']}; --accent:{T['accent']}; "
            f"--grid:{T['grid']}; --kpi-bg:{T['kpi_bg']}; "
            f"--cols:{cols}; --gap:{gap}px; --padding:{padding}px; --row-h:{row_h}px;"
        )

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ {css_vars} }}
{CSS}
.header {{ text-align:center; padding:6px 0 2px; }}
.header h1 {{ font-size:22px; font-weight:700; letter-spacing:1px; }}
.header .sub {{ color:var(--muted); font-size:12px; margin-top:4px; }}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  {f'<div class="sub">{subtitle}</div>' if subtitle else ''}
</div>
<div class="dashboard" style="min-height:{body_h}px;">
{chr(10).join(panels)}
</div>
{_echarts_block(static_dir)}
<script>{JAVASCRIPT}</script>
</body>
</html>
"""

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return {"status": "success", "path": output_path, "warnings": errors}
    except Exception as e:
        import traceback
        return {"status": "error", "errors": [f"渲染失败: {str(e)[:150]}"]}
