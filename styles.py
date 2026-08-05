"""Infolob design system — adapted from AI FinOps Platform shell for Streamlit."""

INFolob_CSS = """
:root {
    --brand: #C0392B;
    --brand-dark: #9A2D20;
    --navy: #1C2B3A;
    --navy-rail: #111B25;
    --canvas: #F5F7FA;
    --card: #FFFFFF;
    --line: #E6EAEF;
    --subtle: #F1F4F7;
    --track: #EEF1F5;
    --hover: #F9FAFB;
    --ink: #1C2B3A;
    --ink-2: #5A6B7B;
    --ink-3: #8A99A8;
    --green: #16A34A;
    --amber: #D97706;
    --danger: #DC2626;
    --shadow: 0 1px 2px rgba(16,24,40,.06), 0 4px 16px rgba(16,24,40,.06);
    --shadow-lg: 0 8px 30px rgba(16,24,40,.12);
    --topbar-h: 60px;
    --rail-w: 236px;
}

html, body, .stApp, .stMarkdown, p, label, div {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* Do not force font on spans — Material Symbols icons rely on their own font.
   Forcing a system font exposes internal ligature names like _arrow_right. */
.stApp p, .stApp label, .stApp .stMarkdown, .il-page-head, .il-panel, .il-kpi,
.il-welcome, .secondary-text, .agent-explanation, .il-meta-line {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

.stApp {
    background: var(--canvas) !important;
    color: var(--ink);
}

/* —— Fixed top bar —— */
.il-topbar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: var(--topbar-h);
    background: var(--navy);
    color: #fff;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 22px;
    z-index: 999999;
    border-bottom: 1px solid rgba(255,255,255,.06);
}
.il-brand { display: flex; align-items: center; gap: 10px; min-width: 206px; }
.il-mark {
    width: 30px; height: 30px; border-radius: 7px;
    background: linear-gradient(140deg, var(--brand), var(--brand-dark));
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 6px rgba(0,0,0,.35);
}
.il-mark span { color: #fff; font-weight: 800; font-size: 18px; line-height: 1; transform: translateY(-1px); }
.il-wm { font-weight: 700; letter-spacing: 3px; font-size: 16px; line-height: 1.15; }
.il-wm small {
    display: block; letter-spacing: 1.1px; font-size: 9px; font-weight: 600;
    color: #9db2c4; margin-top: 2px; text-transform: none;
}
.il-topbar .il-spacer { flex: 1; }
.il-demo-pill {
    background: rgba(255,255,255,.1);
    border: 1px solid rgba(255,255,255,.16);
    color: #dbe4ec;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: .4px;
    padding: 5px 10px;
    border-radius: 999px;
    text-transform: uppercase;
    display: flex;
    align-items: center;
    gap: 6px;
}
.il-demo-pill i {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--brand); display: inline-block;
    animation: il-pulse 2s infinite;
}
@keyframes il-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
.il-avatar {
    width: 32px; height: 32px; border-radius: 50%;
    background: #33475b; color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 12px;
    border: 1px solid rgba(255,255,255,.15);
}

/* —— Hide Streamlit chrome / default multipage nav (belt-and-suspenders) ——
   Primary prevention: .streamlit/config.toml client.showSidebarNavigation=false
   These rules still hide any residual built-in nav if it mounts. */
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
div[data-testid="stSidebarNav"],
section[data-testid="stSidebar"] [data-testid="stSidebarNav"],
section[data-testid="stSidebar"] nav[data-testid="stSidebarNav"],
[data-testid="stSidebarNav"] ul,
[data-testid="stSidebarNavItems"] ul,
[data-testid="stSidebarNavLink"],
[data-testid="stSidebarNavSeparator"] {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
    max-height: 0 !important;
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
    pointer-events: none !important;
}
header[data-testid="stHeader"] {
    background: transparent !important;
    /* Must not clip the reopen control */
    overflow: visible !important;
}
/* Keep toolbar mount point available — Streamlit 1.60 places
   [data-testid="stExpandSidebarButton"] inside stToolbar when collapsed.
   Do NOT display:none the whole toolbar. */
header[data-testid="stHeader"] [data-testid="stToolbar"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    overflow: visible !important;
    pointer-events: none;
}
header[data-testid="stHeader"] [data-testid="stToolbar"] [data-testid="stExpandSidebarButton"] {
    pointer-events: auto !important;
}
#MainMenu, footer, .stDeployButton { visibility: hidden; height: 0; }

/* —— Expanded-rail collapse control (inside dark sidebar) —— */
section[data-testid="stSidebar"] button[data-testid="stSidebarCollapseButton"],
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {
    color: #FFFFFF !important;
    opacity: 1 !important;
    z-index: 999999 !important;
    min-width: 36px !important;
    min-height: 36px !important;
    width: 36px !important;
    height: 36px !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] button[data-testid="stSidebarCollapseButton"]:hover,
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"]:hover {
    background: rgba(255,255,255,0.08) !important;
    color: #FFFFFF !important;
}
section[data-testid="stSidebar"] button[data-testid="stSidebarCollapseButton"] svg,
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] svg,
section[data-testid="stSidebar"] button[data-testid="stSidebarCollapseButton"] span[data-testid="stIconMaterial"] {
    stroke: #FFFFFF !important;
    fill: #FFFFFF !important;
    color: #FFFFFF !important;
    opacity: 1 !important;
}

/* —— Collapsed-sidebar REOPEN control (Streamlit 1.60: stExpandSidebarButton) ——
   Sit below the fixed 60px Infolob top bar so the logo does not cover it. */
[data-testid="stExpandSidebarButton"],
button[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button {
    position: fixed !important;
    top: 72px !important;
    left: 12px !important;
    width: 40px !important;
    height: 40px !important;
    min-width: 40px !important;
    min-height: 40px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: #1C2B3A !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255,255,255,.14) !important;
    border-radius: 8px !important;
    opacity: 1 !important;
    visibility: visible !important;
    z-index: 100000 !important;
    box-shadow:
      0 1px 2px rgba(16,24,40,.12),
      0 4px 16px rgba(16,24,40,.12) !important;
    overflow: visible !important;
    pointer-events: auto !important;
}
[data-testid="stExpandSidebarButton"]:hover,
button[data-testid="stExpandSidebarButton"]:hover,
[data-testid="collapsedControl"]:hover,
[data-testid="stSidebarCollapsedControl"]:hover,
[data-testid="stSidebarCollapsedControl"] button:hover,
[data-testid="collapsedControl"] button:hover {
    background: #243A4E !important;
    color: #FFFFFF !important;
    opacity: 1 !important;
}
[data-testid="stExpandSidebarButton"] svg,
button[data-testid="stExpandSidebarButton"] svg,
[data-testid="collapsedControl"] svg,
[data-testid="stSidebarCollapsedControl"] svg {
    color: #FFFFFF !important;
    stroke: #FFFFFF !important;
    fill: #FFFFFF !important;
    opacity: 1 !important;
}
[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"],
button[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"] {
    color: #FFFFFF !important;
    opacity: 1 !important;
    font-size: 1.25rem !important;
}

/* —— Left rail (Streamlit sidebar) —— */
section[data-testid="stSidebar"] {
    background: var(--navy-rail) !important;
    border-right: 1px solid rgba(255,255,255,.06) !important;
    top: var(--topbar-h) !important;
    height: calc(100vh - var(--topbar-h)) !important;
    width: var(--rail-w) !important;
    min-width: var(--rail-w) !important;
    max-width: 250px !important;
    z-index: 999998 !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
}
section[data-testid="stSidebar"] > div {
    background: var(--navy-rail) !important;
    padding: 8px 0 16px 0 !important;
    width: 100% !important;
    overflow-x: hidden !important;
}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0.1rem !important;
    text-align: left !important;
    display: flex !important;
    flex-direction: column !important;
    min-height: calc(100vh - var(--topbar-h) - 24px);
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-rail-user),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-rail-user) {
    margin-top: auto !important;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"],
section[data-testid="stSidebar"] [data-testid="element-container"] {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] div {
    text-align: left !important;
    color: #C3CED8 !important;
}
.il-rail-group {
    font-size: 10px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: #5F7386 !important;
    margin: 20px 0 8px !important;
    padding: 0 16px !important;
    font-weight: 600;
    text-align: left !important;
}
.il-rail-group:first-child { margin-top: 8px !important; }
.il-rail-user {
    margin: 16px 8px 4px 8px;
    padding: 12px 14px 4px 14px;
    border-top: 1px solid rgba(255,255,255,.06);
    font-size: 12px;
    color: #93a5b6;
    text-align: left !important;
}
.il-rail-user .name {
    color: #eaf1f6 !important;
    font-weight: 600;
    font-size: 13px;
    margin-bottom: 2px;
    text-align: left !important;
}
.il-rail-user .role {
    color: #8ea3b5 !important;
    font-size: 12px;
    margin-bottom: 6px;
    text-align: left !important;
}

section[data-testid="stSidebar"] div[data-testid="stButton"] {
    margin: 2px 8px !important;
    width: calc(100% - 16px) !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
    width: 100% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    text-align: left !important;
    gap: 10px !important;
    background: transparent !important;
    color: #C3CED8 !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 10px 14px !important;
    min-height: 42px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    box-shadow: none !important;
    position: relative !important;
    white-space: nowrap !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button p,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button span {
    text-align: left !important;
    justify-content: flex-start !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
    background: rgba(255,255,255,.05) !important;
    color: #FFFFFF !important;
}
/* Active nav: flag lives in previous element container */
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"] div[data-testid="stButton"] > button,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-nav-active-flag) + [data-testid="element-container"] div[data-testid="stButton"] > button,
.il-nav-active-flag + div[data-testid="stButton"] > button {
    background: linear-gradient(90deg, rgba(192,57,43,0.26), rgba(192,57,43,0.06)) !important;
    color: #FFFFFF !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"] div[data-testid="stButton"] > button::before,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-nav-active-flag) + [data-testid="element-container"] div[data-testid="stButton"] > button::before,
.il-nav-active-flag + div[data-testid="stButton"] > button::before {
    content: "";
    position: absolute;
    left: 0;
    top: 8px;
    bottom: 8px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: #C0392B;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"] div[data-testid="stButton"] > button svg,
.il-nav-active-flag + div[data-testid="stButton"] > button svg {
    stroke: #C0392B !important;
    color: #C0392B !important;
}
/* Hide the zero-height active flag markdown row */
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-nav-active-flag) {
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}
.il-nav-active-flag { display: none !important; }

/* —— Main canvas —— */
.stApp [data-testid="stAppViewContainer"] {
    background: var(--canvas) !important;
}
.stApp [data-testid="stAppViewContainer"] > .main {
    margin-top: var(--topbar-h);
    background: var(--canvas) !important;
}
.block-container {
    padding-top: 1.35rem !important;
    padding-bottom: 3.5rem !important;
    padding-left: 1.6rem !important;
    padding-right: 1.6rem !important;
    max-width: 1280px !important;
}

/* Login: no rail offset feel */
.il-login-wrap {
    max-width: 420px;
    margin: 2.5rem auto 0;
}

/* —— Page head —— */
.il-page-head { margin-bottom: 18px; }
.il-page-head h1 {
    font-size: 21px;
    font-weight: 700;
    letter-spacing: -.2px;
    color: var(--ink);
    margin: 0;
}
.il-page-head p {
    color: var(--ink-2);
    font-size: 13px;
    margin: 3px 0 0 0;
}

/* —— KPI / cards / panels —— */
.il-kpi-row {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 16px;
}
.il-kpi {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 14px 15px;
    box-shadow: var(--shadow);
}
.il-kpi .lab {
    font-size: 11px;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: .4px;
    font-weight: 600;
    margin-bottom: 8px;
}
.il-kpi .val {
    font-size: 22px;
    font-weight: 750;
    letter-spacing: -.5px;
    line-height: 1;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
}
.il-kpi .sub {
    font-size: 11px;
    margin-top: 7px;
    color: var(--ink-2);
}
.il-kpi.accent {
    background: linear-gradient(135deg, var(--brand), var(--brand-dark));
    border: none;
    color: #fff;
}
.il-kpi.accent .lab { color: rgba(255,255,255,.8); }
.il-kpi.accent .val { color: #fff; }
.il-kpi.accent .sub { color: rgba(255,255,255,.9); }

.il-panel {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 16px 18px;
    margin-bottom: 14px;
}
.il-panel-title, .il-panel h3 {
    font-size: 14px;
    font-weight: 700;
    color: var(--ink);
    margin: 0 0 12px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.il-panel-title .hint, .il-panel h3 .hint {
    font-size: 11px;
    color: var(--ink-3);
    font-weight: 500;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--card) !important;
    border: 1px solid var(--line) !important;
    border-radius: 12px !important;
    box-shadow: var(--shadow);
    padding: 8px 6px 4px 6px;
    margin-bottom: 14px;
}
.il-grid-2 {
    display: grid;
    grid-template-columns: 1.55fr 1fr;
    gap: 14px;
    margin-bottom: 14px;
}
.il-field-row {
    display: flex;
    gap: 14px;
    margin: 4px 0 2px;
}
.il-field-meta {
    font-size: 11px;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: .4px;
    font-weight: 600;
    margin-bottom: 4px;
}
.il-meta-line {
    font-size: 12.5px;
    color: var(--ink-2);
    margin-top: 10px;
}
.il-meta-line strong { color: var(--ink); }

.il-pill {
    font-size: 10px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    text-transform: uppercase;
    letter-spacing: .4px;
    display: inline-block;
}
.il-pill.ok { background: #dcfce7; color: #15803d; }
.il-pill.warn { background: #fef3c7; color: #b45309; }
.il-pill.danger { background: #fee2e2; color: #b91c1c; }
.il-pill.neutral { background: var(--subtle); color: var(--ink-2); }

.il-success-card {
    background: color-mix(in srgb, var(--green) 8%, var(--card));
    border: 1px solid color-mix(in srgb, var(--green) 28%, var(--line));
    border-left: 4px solid var(--green);
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 12px;
}
.il-success-card .title {
    font-weight: 700;
    font-size: 14px;
    color: var(--ink);
    margin-bottom: 8px;
}
.il-success-card .row {
    font-size: 13px;
    color: var(--ink-2);
    margin: 3px 0;
}
.il-success-card .row b { color: var(--ink); }

.il-welcome {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 18px 20px;
    max-width: 28rem;
    margin-bottom: 1rem;
}
.il-welcome .lab {
    color: var(--ink-3);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .4px;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.il-welcome .val {
    color: var(--ink);
    font-size: 1.05rem;
    font-weight: 600;
    margin-bottom: 12px;
}
.il-welcome .val:last-child { margin-bottom: 0; }

.secondary-text {
    color: var(--ink-2);
    font-size: 0.88rem;
    text-align: left;
}
.agent-explanation {
    color: var(--ink);
    line-height: 1.55;
    font-size: 0.92rem;
    text-align: left;
    margin: 10px 0 0 0;
}

/* Buttons */
div[data-testid="stButton"] button[kind="primary"],
div[data-testid="stFormSubmitButton"] button {
    background: var(--navy) !important;
    color: #FFFFFF !important;
    border: 1px solid var(--navy) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover,
div[data-testid="stFormSubmitButton"] button:hover {
    background: #243a4e !important;
}
div[data-testid="stButton"] button[kind="secondary"] {
    background: var(--card) !important;
    color: var(--ink) !important;
    border: 1px solid var(--line) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}

/* —— Expander: readable label, no material-icon ligature bleed —— */
div[data-testid="stExpander"] {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
}
div[data-testid="stExpander"] details summary {
    display: flex !important;
    align-items: center !important;
    gap: 0.5rem !important;
    min-height: 44px !important;
    list-style: none !important;
}
div[data-testid="stExpander"] details summary::-webkit-details-marker {
    display: none;
}
div[data-testid="stExpander"] details summary p {
    margin: 0 !important;
    line-height: 1.3 !important;
    color: var(--ink) !important;
}
div[data-testid="stExpander"] details summary svg {
    flex: 0 0 auto;
}
/* Hide internal Material icon *text* if font fails; keep SVG chevrons */
div[data-testid="stExpander"] details summary span[data-testid="stIconMaterial"],
div[data-testid="stExpander"] details summary span.material-symbols-rounded,
div[data-testid="stExpander"] details summary span.material-symbols-outlined {
    font-size: 0 !important;
    width: 1.1rem !important;
    height: 1.1rem !important;
    overflow: hidden !important;
    color: transparent !important;
    speak: never;
}
div[data-testid="stExpander"] details summary span[data-testid="stIconMaterial"]::before,
div[data-testid="stExpander"] details summary span.material-symbols-rounded::before,
div[data-testid="stExpander"] details summary span.material-symbols-outlined::before {
    font-size: 1.1rem !important;
    color: var(--ink-2) !important;
}

@media (max-width: 1250px) {
    .il-kpi-row { grid-template-columns: repeat(3, 1fr); }
    .il-grid-2 { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
    .il-kpi-row { grid-template-columns: repeat(2, 1fr); }
    .il-wm small { display: none; }
    .il-demo-pill { display: none; }
    section[data-testid="stSidebar"] {
        width: 220px !important;
        min-width: 220px !important;
    }
    section[data-testid="stSidebar"] button[data-testid="stSidebarCollapseButton"],
    [data-testid="stExpandSidebarButton"] {
        color: #FFFFFF !important;
        opacity: 1 !important;
        visibility: visible !important;
    }
}
@media (max-width: 700px) {
    .il-kpi-row { grid-template-columns: 1fr; }
    [data-testid="stExpandSidebarButton"],
    button[data-testid="stExpandSidebarButton"] {
        top: 72px !important;
        left: 12px !important;
        z-index: 100000 !important;
    }
}
"""


# Critical rules injected first so default multipage nav never paints visibly.
CRITICAL_SHELL_CSS = """
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
div[data-testid="stSidebarNav"],
[data-testid="stSidebarNavLink"],
[data-testid="stSidebarNavSeparator"] {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
    max-height: 0 !important;
    overflow: hidden !important;
    pointer-events: none !important;
}
"""


def inject_styles() -> str:
    return CRITICAL_SHELL_CSS + INFolob_CSS


def inject_critical_shell_css() -> str:
    """Minimal CSS for the earliest possible bootstrap injection."""
    return CRITICAL_SHELL_CSS
