"""Minimal Streamlit app for Policy & Guardrails AppTests (read-only role)."""

from __future__ import annotations

import streamlit as st

from services import policy_service
from styles import inject_styles
from ui_components import page_heading, panel_title

st.set_page_config(page_title="Policy UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

view = policy_service.get_policy_guardrails_view()
page_heading("Policy & Guardrails", "Read-only business view")
panel_title("Active policy", hint=view["policy_version"])

from html import escape

header = (
    "<div class='il-queue-table il-policy-table'>"
    "<div class='il-queue-head'>"
    "<div>Business Name</div><div>Explanation</div>"
    "<div>Configured Value</div><div>Internal Key</div>"
    "</div>"
)
parts = [header]
for row in view["rules"]:
    parts.append(
        "<div class='il-queue-row'>"
        f"<div>{escape(row['business_name'])}</div>"
        f"<div>{escape(row['explanation'])}</div>"
        f"<div>{escape(row['configured_value'])}</div>"
        f"<div>{escape(row['internal_key'])}</div>"
        "</div>"
    )
parts.append("</div>")
st.markdown("".join(parts), unsafe_allow_html=True)
