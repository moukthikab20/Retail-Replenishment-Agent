"""Infolob brand styling for the replenishment POC."""

INFolob_CSS = """
html, body, [class*="css"] {
    font-family: 'Aptos', 'Segoe UI', system-ui, sans-serif;
    color: #2C3E50;
}

.stApp {
    background-color: #FAFBFC;
}

.block-container {
    padding-top: 1.5rem;
    padding-bottom: 5rem;
    max-width: 1200px;
}

.page-title-wrap {
    display: flex;
    align-items: stretch;
    margin-bottom: 0.25rem;
}

.title-stripe {
    width: 4px;
    background-color: #C0392B;
    margin-right: 14px;
    border-radius: 2px;
    flex-shrink: 0;
}

.page-title {
    font-size: 1.75rem;
    font-weight: 700;
    color: #1C2B3A;
    margin: 0;
    text-decoration: none !important;
    text-align: left;
}

.page-subtitle {
    color: #2C3E50;
    font-size: 0.95rem;
    margin: 0.35rem 0 1.25rem 18px;
    text-align: left;
}

.card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    margin-bottom: 1rem;
    overflow: hidden;
}

.card-header {
    background-color: #1C2B3A;
    color: #FFFFFF;
    padding: 0.65rem 1rem;
    font-weight: 600;
    font-size: 0.95rem;
    text-align: left;
}

.card-body {
    padding: 1rem;
    text-align: left;
}

.stat-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.75rem;
}

.stat-callout {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 0.75rem;
    text-align: left;
}

.stat-label {
    font-size: 0.75rem;
    color: #64748B;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 0.25rem;
}

.stat-value {
    font-size: 1.25rem;
    font-weight: 700;
    color: #1C2B3A;
}

.chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
}

.chip {
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}

.chip-agent {
    background: rgba(124, 58, 237, 0.12);
    color: #7C3AED;
    border: 1px solid rgba(124, 58, 237, 0.25);
}

.chip-forecast {
    background: rgba(13, 148, 136, 0.12);
    color: #0D9488;
    border: 1px solid rgba(13, 148, 136, 0.25);
}

.chip-erp {
    background: rgba(217, 119, 6, 0.12);
    color: #D97706;
    border: 1px solid rgba(217, 119, 6, 0.25);
}

.navy-band {
    background-color: #1C2B3A;
    color: #FFFFFF;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin: 1rem 0;
    text-align: left;
}

.navy-band .band-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    opacity: 0.85;
    margin-bottom: 0.35rem;
}

.navy-band .band-value {
    font-size: 1.5rem;
    font-weight: 700;
}

.recommendation-callout {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-left: 4px solid #7C3AED;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-top: 0.5rem;
    text-align: left;
}

.recommendation-callout h4 {
    color: #1C2B3A;
    margin: 0 0 0.5rem 0;
    font-size: 1rem;
}

.agent-explanation {
    color: #2C3E50;
    line-height: 1.55;
    font-size: 0.92rem;
    text-align: left;
}

.risk-badge {
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    margin-right: 0.35rem;
}

.risk-stockout {
    background: rgba(192, 57, 43, 0.1);
    color: #C0392B;
    border: 1px solid rgba(192, 57, 43, 0.25);
}

.risk-balanced {
    background: rgba(13, 148, 136, 0.1);
    color: #0D9488;
    border: 1px solid rgba(13, 148, 136, 0.25);
}

.risk-overstock {
    background: rgba(217, 119, 6, 0.1);
    color: #D97706;
    border: 1px solid rgba(217, 119, 6, 0.25);
}

.footer-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background-color: #1C2B3A;
    color: #FFFFFF;
    padding: 0.65rem 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.8rem;
    z-index: 999;
}

.footer-brand {
    font-weight: 700;
    letter-spacing: 0.12em;
}

.approval-row {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-top: 1rem;
}

div[data-testid="stButton"] button[kind="primary"] {
    background-color: #1C2B3A !important;
    color: #FFFFFF !important;
    border: none !important;
}

div[data-testid="stButton"] button[kind="secondary"] {
    background-color: #FFFFFF !important;
    color: #1C2B3A !important;
    border: 1px solid #E2E8F0 !important;
}

.secondary-text {
    color: #2C3E50;
    font-size: 0.88rem;
    text-align: left;
}

.po-record {
    background: #FFFBEB;
    border: 1px solid #E2E8F0;
    border-left: 4px solid #D97706;
    border-radius: 6px;
    padding: 0.85rem 1rem;
    margin-top: 0.75rem;
    text-align: left;
    font-size: 0.88rem;
}
"""


def inject_styles() -> str:
    return INFolob_CSS
