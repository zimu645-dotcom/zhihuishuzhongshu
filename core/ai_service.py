"""
智汇中枢 - AI 服务层
使用标准库 urllib 调用 API，稳定可靠
"""

import json
import time
import ssl
import urllib.request
import urllib.error
from typing import Optional, Callable


SYSTEM_PROMPT = """你是"智汇中枢"智能知识工作台的AI助手。

规则：
1. **闲聊**：用户打招呼、问好时，正常聊天。
2. **分析**：用户提到"分析""总结""整理"时，直接用已选知识库的数据做详细分析，格式要清晰整齐。
3. **图表和PPT**：仅当用户明确说"生成图表""画图""可视化""做PPT""演示文稿"时才生成。用户没说就不要自作主张。
4. **可视化大屏**：当用户说"生成大屏""数据大屏""可视化大屏""数据看板""dashboard"时，调用 generate_dashboard 制作 HTML 大屏。必须使用用户消息里[数据预览]中的真实列名和数值，绝不自造数据；分类维度只取 Top 8；图表数据必须是聚合后的小数据（不要输出原始全表）；组件不超过15个；布局用 24 列网格的 x/y/w/h 定位。
5. **调整大屏**：用户要求调整/优化已有大屏（换主题、换图表类型、改布局、加组件、改颜色）时，基于用户消息里的[上一版大屏 spec]修改，输出一份完整的全新 spec（不是 diff），再次调用 generate_dashboard。
6. **工具**：需要时用 [TOOL] 命令调用。

工具格式：
[TOOL]
{"name": "generate_chart", "args": {"chart_type": "bar", "title": "标题", "data": {"labels": ["A","B"], "values": [10,20]}}}
[/TOOL]
[TOOL]
{"name": "web_search", "args": {"query": "搜索关键词"}}
[/TOOL]
[TOOL]
{"name": "generate_ppt", "args": {"title": "标题", "slides": [{"title":"页1","content":["要点"]}]}}
[/TOOL]
[TOOL]
{"name": "generate_dashboard", "args": {"spec": {
  "title": "销售驾驶舱", "theme": "dark",
  "page": {"cols": 24, "row_height": 60, "gap": 12},
  "components": [
    {"type": "kpi", "x":0,"y":1,"w":6,"h":3,"title":"总销售额","value":1289000,"unit":"元","delta":12.5,"delta_label":"较上月"},
    {"type": "line", "x":0,"y":4,"w":12,"h":6,"title":"月度趋势","data":{"categories":["1月","2月"],"series":[{"name":"销售额","data":[120,200]}]}},
    {"type": "donut", "x":12,"y":4,"w":6,"h":6,"title":"渠道占比","data":{"items":[{"name":"线上","value":60},{"name":"线下","value":40}]}}
  ]
}}}
[/TOOL]

spec 组件 type 可选：kpi, bar, hbar, line, area, pie, donut, radar, scatter, bubble, heatmap, gauge, funnel, table, rank, text, divider。gauge 用 value/max/unit 定义。每个组件用 x/y/w/h 定位（24列网格），数据只放聚合后的少量结果。

【已安装技能】
{skills}"""


def _get_system_prompt() -> str:
    """获取动态系统提示词（含技能）"""
    try:
        from core.skill_manager import get_enabled_prompts
        skills = get_enabled_prompts()
    except Exception:
        skills = ""
    return SYSTEM_PROMPT.replace("{skills}", skills or "（暂无）")


class AIService:
    """AI 服务 - 使用标准库 urllib"""

    def __init__(self, db):
        self.db = db

    def get_model_config(self, model_key: str = "text_analysis") -> Optional[dict]:
        from app.database import ModelConfigDB
        with self.db.session() as s:
            cfg = s.query(ModelConfigDB).filter(
                ModelConfigDB.model_key == model_key,
                ModelConfigDB.enabled == True
            ).first()
            if cfg and cfg.api_key:
                return {
                    "api_key": cfg.api_key,
                    "api_base": cfg.api_base.rstrip("/") if cfg.api_base else "https://api.deepseek.com",
                    "model_name": cfg.model_name or "deepseek-chat",
                }
        return None

    def clear_client_cache(self):
        pass

    def chat(self, messages, model_key="text_analysis", stream_callback=None,
             knowledge_base_id=None, images=None):
        """调用大模型 API"""
        config = self.get_model_config(model_key)
        if not config:
            self.db.add_log("ERROR", "ai", "no_config",
                            f"模型未配置 [key={model_key}]")
            return "⚠️ 未配置模型\n\n请先在「大模型配置」页面填写 API 密钥和地址。"

        url = f"{config['api_base'].rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}
        fm = self._build_messages(messages, images)
        system_prompt = _get_system_prompt()
        body = {
            "model": config["model_name"],
            "messages": [{"role": "system", "content": system_prompt}] + fm,
            "stream": bool(stream_callback),
            "max_tokens": 16384,
            "temperature": 0.7,
        }
        # Kimi/Moonshot 只接受 temperature=1
        model_name = config.get("model_name", "").lower()
        api_base = config.get("api_base", "").lower()
        if "moonshot" in model_name or "kimi" in model_name or "moonshot" in api_base:
            body["temperature"] = 1

        data = json.dumps(body).encode()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        try:
            st = time.time()
            if stream_callback:
                # ── 流式输出：逐步回调增量，最后返回累积完整文本 ──
                full = ""
                timeout = 600  # 流式长输出放宽超时
                with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers),
                                            timeout=timeout, context=ctx) as resp:
                    for raw in resp:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            obj = json.loads(payload)
                            delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                            if delta:
                                full += delta
                                stream_callback(delta)
                        except Exception:
                            continue
                el = int((time.time() - st) * 1000)
                self.db.add_log("INFO", "ai", "ok", f"AI回复(流式 {len(full)}字)", duration_ms=el)
                return full
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120, context=ctx) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"].get("content", "")
            el = int((time.time() - st) * 1000)
            self.db.add_log("INFO", "ai", "ok", f"AI回复({len(content)}字)", duration_ms=el)
            return content
        except urllib.error.HTTPError as e:
            b = ""
            try: b = e.read().decode("utf-8", errors="replace")[:200]
            except: pass
            self.db.add_log("ERROR", "ai", "http_err", f"HTTP {e.code}", detail={"code": e.code, "body": b})
            if e.code == 401: return "⚠️ API密钥无效，请检查大模型配置"
            if e.code == 429: return "⏳ 请求频率限制，请稍后再试"
            # temperature 不兼容时用 1 重试（重试走非流式）
            if e.code == 400 and "temperature" in b.lower():
                retry_body = dict(body)
                retry_body["temperature"] = 1
                retry_body["stream"] = False
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(retry_body).encode(), headers=headers), timeout=120, context=ctx) as resp2:
                        result2 = json.loads(resp2.read().decode("utf-8"))
                    return result2["choices"][0]["message"].get("content", "")
                except Exception:
                    pass
            return f"⚠️ HTTP {e.code}: {b[:100]}"
        except urllib.error.URLError as e:
            r = str(e.reason)
            self.db.add_log("ERROR", "ai", "url_err", r[:80])
            return "⏱️ 连接超时" if "timed out" in r.lower() else f"⚠️ 网络异常: {r[:80]}"
        except Exception as e:
            import traceback
            self.db.add_log("ERROR", "ai", "unknown", str(e)[:100], detail={"trace": traceback.format_exc()[:200]})
            return f"⚠️ 请求失败: {str(e)[:100]}"

    def _build_messages(self, messages, images=None):
        r = []
        has_images = images and len(images) > 0
        for m in messages:
            if has_images and m["role"] == "user":
                import base64
                p = [{"type": "text", "text": m["content"]}]
                for img in images:
                    with open(img["path"], "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    ext = img["path"].rsplit(".", 1)[-1].lower()
                    p.append({"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}", "detail": img.get("detail", "auto")}})
                r.append({"role": "user", "content": p})
            else:
                r.append(m)
        return r

    def classify_task(self, user_input: str) -> str:
        """智能选择已启用的模型"""
        try:
            from app.database import ModelConfigDB
            with self.db.session() as s:
                configs = s.query(ModelConfigDB).filter(
                    ModelConfigDB.enabled == True,
                    ModelConfigDB.api_key.isnot(None),
                    ModelConfigDB.api_key != ""
                ).all()
                enabled = set(c.model_key for c in configs)
        except Exception:
            enabled = set()

        _in = user_input.lower()  # 统一小写匹配

        # 图表/PPT 关键词 → 用 chart_ppt 模型
        if "chart_ppt" in enabled:
            chart_kw = ["图表", "图", "可视化", "ppt", "演示文稿", "柱状图", "折线图", "饼图", "画图",
                        "大屏", "看板", "dashboard"]
            for kw in chart_kw:
                if kw in _in:
                    return "chart_ppt"

        # 图片相关 → 优先用 vision
        if "vision" in enabled:
            vision_kw = ["图片", "图像", "照片", "截图", "扫描件", "识别", "看这张", "图里"]
            for kw in vision_kw:
                if kw in _in:
                    return "vision"

        # 代码相关 → 优先用 code
        if "code" in enabled:
            code_kw = ["代码", "编程", "函数", "bug", "写一个", "python"]
            for kw in code_kw:
                if kw in _in:
                    return "code"

        # 默认用 text_analysis，没有则用第一个启用的模型
        if "text_analysis" in enabled:
            return "text_analysis"
        if enabled:
            return list(enabled)[0]
        return "text_analysis"
