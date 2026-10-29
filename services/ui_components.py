"""
FestivePulse — Reusable UI Components, Standard Sidebar & Theming for Streamlit
Designed for nontechnical Indian shopkeepers with high accessibility and clear visual cues.
"""

from typing import Optional
import streamlit as st
from config import ASSETS_DIR, APP_VERSION
from services.festival_service import get_current_festival
from database.queries import get_business_settings

# Developer Profile Constants
DEVELOPER_NAME = "Audi Siva Bhanuvardhan Sarvepalli"
LINKEDIN_URL = "https://www.linkedin.com/in/audi-siva-bhanuvardhan-sarvepalli-4598a8289/"


def apply_custom_css():
    """
    Injects custom festive styles from assets/custom.css.
    """
    css_path = ASSETS_DIR / "custom.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def render_festival_header():
    """
    Renders an informative top banner showing active festival, dates, and campaign phase.
    """
    fest = get_current_festival()
    settings = get_business_settings()
    store_name = settings.get("business_name", "FestivePulse Retailers")

    if fest:
        fest_name = fest["festival_name"]
        year = fest["year"]
        status_text = fest["status_text"]
        days_to_fest = fest["days_to_festival"]
        
        countdown_str = f"<b>{days_to_fest} Days to Festival</b>" if days_to_fest >= 0 else "<b>Festival Concluded</b>"

        st.markdown(f"""
        <div class="festival-hero-banner">
            <div>
                <span class="festival-badge">Active Festival Campaign</span>
                <h3 style="margin: 0.35rem 0 0.15rem 0; color: #FFFFFF; font-size: 1.3rem;">
                    🪔 {fest_name} ({year})
                </h3>
                <span style="color: #FCD34D; font-size: 0.85rem; font-weight: 500;">
                    {status_text} • Window: {fest['campaign_start_date']} to {fest['campaign_end_date']}
                </span>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 1.15rem; color: #FFFFFF;">{countdown_str}</div>
                <div style="font-size: 0.78rem; color: #CBD5E1;">{store_name}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="festival-hero-banner">
            <div>
                <span class="festival-badge">Off-Season Mode</span>
                <h3 style="margin: 0.35rem 0 0.15rem 0; color: #FFFFFF; font-size: 1.25rem;">
                    🏪 {store_name}
                </h3>
                <span style="color: #94A3B8; font-size: 0.85rem;">
                    Standard operational mode. Activate a festival in Festival Management to enable surge planning.
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)


def render_standard_sidebar():
    """
    Renders a unified, professional sidebar across every page:
    - Store Profile & GSTIN status
    - Active Campaign Status
    - Developer credit with LinkedIn link
    """
    settings = get_business_settings()
    store_name = settings.get("business_name", "FestivePulse Retailers")
    gstin = settings.get("gstin", "")
    region = settings.get("primary_region", "South")
    state = settings.get("state", "Karnataka")
    
    fest = get_current_festival()

    with st.sidebar:
        # 1. Store Header Card
        st.markdown(f"""
        <div class="sidebar-profile-card">
            <div style="font-size: 0.75rem; text-transform: uppercase; color: #D97706; font-weight: 700; letter-spacing: 0.05em;">
                🏪 Active Store
            </div>
            <div style="font-size: 1.05rem; font-weight: 700; color: #FFFFFF; margin-top: 0.15rem;">
                {store_name}
            </div>
            <div style="font-size: 0.78rem; color: #94A3B8; margin-top: 0.2rem;">
                GSTIN: <code style="color: #FDE68A; background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 4px;">{gstin if gstin else 'Unregistered'}</code>
            </div>
            <div style="font-size: 0.75rem; color: #CBD5E1; margin-top: 0.2rem;">
                📍 {region} India • {state}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 2. Festival Campaign Status
        if fest:
            d_to_f = fest["days_to_festival"]
            d_msg = f"{d_to_f} days away" if d_to_f >= 0 else "Concluded"
            st.info(f"🪔 **Active Campaign: {fest['festival_name']}**\n\n*{fest['status_text']} ({d_msg})*")
        else:
            st.caption("🏪 *Currently in regular off-season mode.*")

        st.markdown("---")

        # 3. Developer & LinkedIn Credit Card
        st.markdown(f"""
        <div class="sidebar-footer-card">
            <div style="font-size: 0.72rem; text-transform: uppercase; color: #94A3B8; font-weight: 600; letter-spacing: 0.04em;">
                Crafted for Indian Retailers
            </div>
            <div style="font-size: 0.88rem; font-weight: 700; color: #F8FAFC; margin-top: 0.2rem;">
                {DEVELOPER_NAME}
            </div>
            <div style="font-size: 0.75rem; color: #64748B; margin-top: 0.15rem;">
                FestivePulse v{APP_VERSION} • Pure Python & SQLite
            </div>
            <a href="{LINKEDIN_URL}" target="_blank" class="linkedin-btn">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/>
                </svg>
                Connect on LinkedIn
            </a>
        </div>
        """, unsafe_allow_html=True)


def render_kpi_card(label: str, value: str, subtext: str = "", delta: str = None, is_good: bool = True):
    """
    Renders a styled metric card with clear typography and contrast.
    """
    delta_html = ""
    if delta:
        delta_color = "#34D399" if is_good else "#FB7185"
        delta_html = f"<span style='color: {delta_color}; font-size: 0.8rem; font-weight: 600;'>{delta}</span>"

    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div class="metric-subtext">{subtext}</div>
            {delta_html}
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_empty_state(title: str, message: str, action_label: Optional[str] = None, action_page: Optional[str] = None, icon: str = "📭"):
    """
    Renders a clear, actionable empty state for nontechnical shopkeepers.
    """
    st.markdown(f"""
    <div class="empty-state-box">
        <div class="empty-state-icon">{icon}</div>
        <div class="empty-state-title">{title}</div>
        <div class="empty-state-text">{message}</div>
    </div>
    """, unsafe_allow_html=True)
    if action_label and action_page:
        col_c1, col_c2, col_c3 = st.columns([1, 1.2, 1])
        with col_c2:
            st.page_link(action_page, label=action_label, type="primary")


def get_festive_plotly_layout() -> dict:
    """
    Returns standard dark theme and accessible color palette for Plotly charts.
    """
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Plus Jakarta Sans, sans-serif", color="#CBD5E1"),
        margin=dict(l=20, r=20, t=35, b=20),
        xaxis=dict(
            gridcolor="rgba(255, 255, 255, 0.08)",
            zerolinecolor="rgba(255, 255, 255, 0.12)"
        ),
        yaxis=dict(
            gridcolor="rgba(255, 255, 255, 0.08)",
            zerolinecolor="rgba(255, 255, 255, 0.12)"
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#F8FAFC")
        )
    )
