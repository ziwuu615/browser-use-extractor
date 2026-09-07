"""Streamlit 界面：浏览器里输入 URL + 字段，一键采集并展示结果。

启动：
    streamlit run app/ui.py
"""
import json

import streamlit as st

from app.extractor import extract_sync

st.set_page_config(page_title="网页数据采集 Agent", layout="wide")
st.title("🧭 网页结构化数据采集 Agent")
st.caption("基于 browser-use + DeepSeek（文本/DOM 模式），自然语言描述即可采集任意网页的结构化数据")

url = st.text_input("目标网页 URL", value="https://arxiv.org/list/cs.AI/recent")
fields = st.text_input("要提取的字段（逗号分隔）", value="title, authors")
max_steps = st.slider("最大步数", 5, 60, 20)
headless = st.checkbox("无头模式", value=True)
use_vision = st.checkbox("视觉模式（需 Qwen-VL / GLM-4V Key）", value=False)

if st.button("开始采集", type="primary"):
    field_list = [f.strip() for f in fields.split(",") if f.strip()]
    with st.spinner("Agent 正在打开网页并采集数据…"):
        result = extract_sync(url=url, fields=field_list or None,
                              max_steps=max_steps, headless=headless,
                              use_vision=use_vision or None)
    if result.success:
        st.success(f"采集成功 · 耗时 {result.duration_s}s · 用了 {result.steps} 步")
        st.json(result.data)
    else:
        st.error("采集失败")
        if result.errors:
            st.code("\n".join(result.errors))
        st.code(result.raw or "(无输出)")
    st.download_button("下载 JSON", json.dumps(result.data, ensure_ascii=False, indent=2),
                       file_name="extract_result.json")
