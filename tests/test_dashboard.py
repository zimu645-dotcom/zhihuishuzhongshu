# -*- coding: utf-8 -*-
"""
可视化大屏渲染器单元测试
运行：.venv/Scripts/python.exe -m unittest tests.test_dashboard -v
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dashboard import (validate_spec, render_dashboard, extract_structured_data,
                            build_data_preview)

SAMPLE_SPEC = {
    "title": "销售驾驶舱", "theme": "dark",
    "page": {"cols": 24, "row_height": 60, "gap": 12},
    "components": [
        {"type": "kpi", "x": 0, "y": 1, "w": 6, "h": 3, "title": "总销售额",
         "value": 1289000, "unit": "元", "delta": 12.5, "delta_label": "较上月"},
        {"type": "line", "x": 0, "y": 4, "w": 12, "h": 6, "title": "月度趋势",
         "data": {"categories": ["1月", "2月"], "series": [{"name": "销售额", "data": [120, 200]}]}},
        {"type": "donut", "x": 12, "y": 4, "w": 6, "h": 6, "title": "渠道占比",
         "data": {"items": [{"name": "线上", "value": 60}, {"name": "线下", "value": 40}]}},
        {"type": "gauge", "x": 18, "y": 4, "w": 6, "h": 5, "title": "目标完成率",
         "value": 85, "max": 100, "unit": "%"},
        {"type": "rank", "x": 0, "y": 10, "w": 12, "h": 5, "title": "TOP8",
         "items": [{"name": "华东", "value": 320}, {"name": "华南", "value": 280}]},
    ],
}


class DashboardRendererTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="dash_test_")
        self.html_path = os.path.join(self.tmpdir, "dashboard_test.html")

    def test_render_basic_dashboard(self):
        spec = json_loads(json_dumps(SAMPLE_SPEC))
        r = render_dashboard(spec, self.html_path, static_dir=None)
        self.assertEqual(r["status"], "success")
        self.assertTrue(os.path.exists(self.html_path))
        with open(self.html_path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn('<meta charset="utf-8">', html)
        self.assertIn("echarts", html.lower())
        # line + donut + gauge = 3 个 ECharts 容器
        self.assertEqual(html.count('class="chart"'), 3)

    def test_validate_defaults(self):
        spec = {"components": [{"type": "bar", "data": {"categories": ["A"],
                                                        "series": [{"name": "s", "data": [1]}]}}]}
        self.assertEqual(validate_spec(spec), [])
        self.assertEqual(spec["title"], "AI可视化大屏")  # 缺 title 补默认
        self.assertEqual(spec["theme"], "dark")

    def test_validate_unknown_type_skipped(self):
        spec = {"components": [{"type": "bogus"}, {"type": "kpi", "title": "t", "value": 1}]}
        errs = validate_spec(spec)
        self.assertEqual(errs, [])
        self.assertTrue(spec["components"][0].get("_skipped"))

    def test_validate_missing_data(self):
        spec = {"components": [{"type": "bar", "title": "无数据"}]}
        errs = validate_spec(spec)
        self.assertTrue(any("缺少 data" in e for e in errs))

    def test_gauge_no_data_needed(self):
        spec = {"components": [{"type": "gauge", "title": "g", "value": 50, "max": 100}]}
        self.assertEqual(validate_spec(spec), [])

    def test_xss_escape(self):
        spec = {"title": "t", "components": [
            {"type": "text", "x": 0, "y": 0, "text": "<script>alert(1)</script>"},
        ]}
        r = render_dashboard(spec, self.html_path, static_dir=None)
        self.assertEqual(r["status"], "success")
        with open(self.html_path, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_auto_layout_no_xy(self):
        spec = {"components": [
            {"type": "kpi", "w": 6, "h": 3, "title": "a", "value": 1},
            {"type": "kpi", "w": 6, "h": 3, "title": "b", "value": 2},
        ]}
        self.assertEqual(validate_spec(spec), [])
        self.assertEqual(spec["components"][0]["x"], 0)
        self.assertEqual(spec["components"][1]["x"], 6)


class DashboardDataExtractTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="dash_data_")

    def test_extract_xlsx(self):
        import pandas as pd
        path = os.path.join(self.tmpdir, "s.xlsx")
        pd.DataFrame({"月份": ["1月", "2月", "3月"], "销售额": [100, 200, 300]}).to_excel(path, index=False)
        sd = extract_structured_data(path, "xlsx")
        self.assertEqual(sd["status"], "success")
        sheet = sd["sheets"][0]
        self.assertEqual(sheet["columns"], ["月份", "销售额"])
        self.assertEqual(sheet["column_types"]["销售额"], "numeric")
        self.assertEqual(sheet["column_types"]["月份"], "string")
        pv = build_data_preview(sd)
        self.assertIn("销售额", pv)
        self.assertIn("100", pv)

    def test_unsupported_type(self):
        sd = extract_structured_data("whatever.txt", "txt")
        self.assertEqual(sd["status"], "error")


class DashboardServerTest(unittest.TestCase):

    def test_start_url_stop(self):
        from core.dashboard_server import DashboardServer
        import tempfile as tf
        server = DashboardServer()
        tmp = tf.mkdtemp(prefix="dash_serve_")
        port = server.start(tmp)
        self.assertGreater(port, 0)
        url = server.url_for("abc.html")
        self.assertIn(f"http://127.0.0.1:{port}/abc.html", url)
        server.stop()
        self.assertFalse(server.running)


def json_dumps(obj):
    import json
    return json.dumps(obj)


def json_loads(obj):
    import json
    return json.loads(obj)


if __name__ == "__main__":
    unittest.main()
