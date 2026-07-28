"""Shared CSS and small presentation helpers."""
from __future__ import annotations

import streamlit as st

# HDFC's brand palette: navy and red.
CSS = """
<style>
  .block-container { padding-top: 2rem; max-width: 1500px; }

  .hdfc-header {
      background: linear-gradient(90deg, #004C8F 0%, #00355F 100%);
      padding: 1rem 1.4rem; border-radius: 8px; margin-bottom: 1.2rem;
      border-left: 6px solid #ED232A;
  }
  .hdfc-header h1 { color: #fff; margin: 0; font-size: 1.55rem; letter-spacing: -0.01em; }
  .hdfc-header p  { color: #C7DCF0; margin: .25rem 0 0; font-size: .86rem; }

  .badge {
      display: inline-block; padding: .12rem .5rem; border-radius: 10px;
      font-size: .7rem; font-weight: 600; margin-right: .3rem; white-space: nowrap;
  }
  .badge-new        { background:#E8F0FA; color:#004C8F; }
  .badge-processing { background:#FFF3DC; color:#8A5A00; }
  .badge-answered   { background:#E3F5E9; color:#136B3A; }
  .badge-type1      { background:#EDE9FB; color:#4B32A8; }
  .badge-type2      { background:#FDE8E9; color:#A81E24; }
  .badge-muted      { background:#EEF1F4; color:#5A6672; }

  .email-body {
      background:#F7F9FB; border:1px solid #E3E8EE; border-radius:6px;
      padding:.9rem 1.1rem; white-space:pre-wrap; font-size:.9rem; line-height:1.55;
  }
  .agent-path {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size:.82rem; background:#F7F9FB; border:1px solid #E3E8EE;
      border-radius:6px; padding:.55rem .8rem;
  }
  .agent-path .skipped { color:#98A2AE; text-decoration: line-through; }
</style>
"""

_STATUS_LABELS = {"new": "New", "processing": "Processing", "answered": "Answered"}
_INTENT_LABELS = {"type_1": "Type 1 · Product info", "type_2": "Type 2 · Account specific"}


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def status_badge(status: str) -> str:
    label = _STATUS_LABELS.get(status, status)
    return f'<span class="badge badge-{status}">{label}</span>'


def intent_badge(intent_type: str | None) -> str:
    if not intent_type:
        return '<span class="badge badge-muted">Unclassified</span>'
    cls = "badge-type1" if intent_type == "type_1" else "badge-type2"
    return f'<span class="badge {cls}">{_INTENT_LABELS.get(intent_type, intent_type)}</span>'


def mask_account(account_number: str | None) -> str:
    """Never render a full account number in the RM console."""
    if not account_number:
        return "—"
    return f"XXXX XXXX {account_number[-4:]}"
