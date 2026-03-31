import streamlit as st


def ApplyGlobalTheme() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(148, 163, 184, 0.20);
            min-width: 300px;
            max-width: 340px;
        }
        .block-container {
            padding-top: 1.25rem;
        }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 12px;
            padding: 10px;
            background: rgba(15, 23, 42, 0.25);
        }
        .stButton button {
            border-radius: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

