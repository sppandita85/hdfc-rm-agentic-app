"""Right pane, top: the email itself plus the customer-context card."""
from __future__ import annotations

import html

import streamlit as st

from ui import styles


def render(row: dict) -> None:
    st.markdown(
        f"{styles.status_badge(row['status'])}{styles.intent_badge(row['intent_type'])}",
        unsafe_allow_html=True,
    )
    st.subheader(row["subject"])
    st.caption(
        f"From **{row.get('customer_name') or 'Unknown sender'}** "
        f"<{row['customer_email']}> · received {row['received_at']:%d %b %Y, %H:%M}"
    )

    st.markdown(f'<div class="email-body">{html.escape(row["body"])}</div>', unsafe_allow_html=True)

    st.markdown("")
    if row.get("customer_id"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Customer", row["customer_name"])
        c2.metric("Account", styles.mask_account(row.get("account_number")))
        c3.metric("Phone", row.get("phone") or "—")
        kyc = row.get("kyc_status") or "unknown"
        c4.metric("KYC", kyc.title())
        if kyc != "verified":
            st.warning(
                f"This customer's KYC is **{kyc}**. In a production system this would gate "
                "account-specific disclosures — see the authentication stub note.",
                icon="⚠️",
            )
    else:
        st.info(
            f"Sender `{row['customer_email']}` does not match any customer on record.",
            icon="ℹ️",
        )
