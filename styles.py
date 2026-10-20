"""Infolob design system — adapted from AI FinOps Platform shell for Streamlit."""

INFolob_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {
    --brand: #C0392B;
    --brand-dark: #9A2D20;
    --navy: #1C2B3A;
    --navy-rail: #111B25;
    --brand-orange: #F97316;
    --canvas: #F7F8FA;
    --card: #FFFFFF;
    --line: #E5E7EB;
    --subtle: #F1F4F7;
    --track: #EEF1F5;
    --hover: #F3F4F6;
    --ink: #111827;
    --ink-2: #4B5563;
    --ink-3: #9CA3AF;
    --radius-card: 12px;
    --transition: 200ms ease;
    --shadow-hover: 0 4px 12px rgba(16,24,40,.08);
    --green: #16A34A;
    --amber: #D97706;
    --danger: #DC2626;
    --status-success: #15803d;
    --status-success-bg: #dcfce7;
    --status-attention: #b45309;
    --status-attention-bg: #fef3c7;
    --status-warning: #a16207;
    --status-warning-bg: #fef9c3;
    --status-critical: #b91c1c;
    --status-critical-bg: #fee2e2;
    --status-progress: #1d4ed8;
    --status-progress-bg: #dbeafe;
    --status-neutral: #5A6B7B;
    --status-neutral-bg: #F1F4F7;
    --shadow: 0 1px 2px rgba(16,24,40,.06), 0 4px 16px rgba(16,24,40,.06);
    --shadow-lg: 0 8px 30px rgba(16,24,40,.12);
    --topbar-h: 64px;
    --rail-w: 252px;
    /* Typography scale — use these; avoid arbitrary inline sizes */
    /* Enterprise type scale — four sizes (+ KPI) */
    --type-page: 28px;
    --type-section: 20px;
    --type-body: 15px;
    --type-caption: 12px;
    --type-card: 12px;
    --type-kpi: 28px;
    --type-kpi-label: 12px;
    --type-table: 14px;
    --type-table-head: 12px;
    --weight-page: 600;
    --weight-section: 600;
    --weight-card: 500;
    --weight-kpi: 600;
    /* Spacing scale */
    --space-1: 4px;
    --space-2: 8px;
    --space-3: 12px;
    --space-4: 16px;
    --space-5: 20px;
    --space-page-top: 16px;
    --space-page-bottom: 28px;
    --row-h: 48px;
}

html, body, .stApp, .stMarkdown, p, label, div {
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* Do not force font on spans — Material Symbols icons rely on their own font.
   Forcing a system font exposes internal ligature names like _arrow_right. */
.stApp p, .stApp label, .stApp .stMarkdown, .il-page-head, .il-panel, .il-kpi,
.il-welcome, .secondary-text, .agent-explanation, .il-meta-line {
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
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
    isolation: isolate;
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
.il-status-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-left: 6px; /* ~18–24px from logo with topbar gap */
    padding: 12px 18px;
    border-radius: 999px;
    background: #2A3D52;
    border: 1px solid rgba(255,255,255,.14);
    color: #fff;
    font-size: 13.5px;
    font-weight: 500;
    line-height: 1.2;
    max-width: min(640px, 52vw);
    min-width: 0;
    overflow: hidden;
}
.il-status-pill .il-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #22C55E;
    flex-shrink: 0;
    box-shadow: 0 0 0 2px rgba(34,197,94,.18);
}
.il-status-pill .il-status-text {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}
@media (max-width: 1100px) {
    .il-status-pill { display: none; }
}
.il-topbar-now {
    color: #9db2c4;
    font-size: 13.5px;
    font-weight: 500;
    line-height: 1.2;
    white-space: nowrap;
    flex-shrink: 0;
}
.il-demo-pill {
    background: rgba(255,255,255,.1);
    border: 1px solid rgba(255,255,255,.16);
    color: #dbe4ec;
    font-size: 12px;
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
    flex-shrink: 0;
}
.il-topbar-user {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
}
.il-topbar-user-name {
    color: #dbe4ec;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
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
    display: none !important;
    pointer-events: none !important;
}
#MainMenu, footer, .stDeployButton { visibility: hidden; height: 0; }

/* —— Hide sidebar collapse / expand chevrons (rail stays fixed & visible) —— */
section[data-testid="stSidebar"] button[data-testid="stSidebarCollapseButton"],
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stExpandSidebarButton"],
button[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    width: 0 !important;
    height: 0 !important;
    min-width: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}

/* —— Left rail (Streamlit sidebar) —— */
section[data-testid="stSidebar"] {
    background: var(--navy-rail) !important;
    border-right: 1px solid rgba(255,255,255,.06) !important;
    top: var(--topbar-h) !important;
    height: calc(100vh - var(--topbar-h)) !important;
    width: var(--rail-w) !important;
    min-width: var(--rail-w) !important;
    max-width: 260px !important;
    z-index: 999998 !important;
    overflow-x: hidden !important;
    overflow-y: hidden !important;
    scrollbar-width: none !important;
}
section[data-testid="stSidebar"]::-webkit-scrollbar {
    width: 0 !important;
    height: 0 !important;
    display: none !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"],
section[data-testid="stSidebar"] header[data-testid="stHeader"] {
    min-height: 0 !important;
    height: 0 !important;
    max-height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
    border: none !important;
}
/* Height + flex chain down to the stretch shell (real layout parent) */
section[data-testid="stSidebar"] > div {
    background: var(--navy-rail) !important;
    padding: 12px 12px 0 12px !important;
    width: 100% !important;
    height: 100% !important;
    max-height: 100% !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
    overflow-y: hidden !important;
    scrollbar-width: none !important;
    display: flex !important;
    flex-direction: column !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    height: 100% !important;
    max-height: 100% !important;
    overflow-x: hidden !important;
    overflow-y: hidden !important;
    scrollbar-width: none !important;
    display: flex !important;
    flex-direction: column !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    height: 100% !important;
    max-height: 100% !important;
    overflow-x: hidden !important;
    overflow-y: hidden !important;
    scrollbar-width: none !important;
    display: grid !important;
    grid-template-rows: minmax(0, 1fr) !important;
    flex: 1 1 0 !important;
    min-height: 0 !important;
    align-self: stretch !important;
}
section[data-testid="stSidebar"] > div::-webkit-scrollbar,
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar,
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]::-webkit-scrollbar {
    width: 0 !important;
    height: 0 !important;
    display: none !important;
}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
    row-gap: 0 !important;
    text-align: left !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: stretch !important;
    justify-content: flex-start !important;
    width: 100% !important;
    overflow: visible !important;
}
/* Top-level sidebar block + anonymous wrapper: fill rail height via grid cell */
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"],
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > :has(> [data-testid="stVerticalBlock"]) {
    min-height: 100% !important;
    height: 100% !important;
    align-self: stretch !important;
    display: flex !important;
    flex-direction: column !important;
}
/*
 * Rail column flex parent: top-level stVerticalBlock inside stSidebarUserContent.
 * Nav and footer st.sidebar.container wrappers are direct sibling stLayoutWrappers.
 */
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > :has(> [data-testid="stVerticalBlock"]) > [data-testid="stVerticalBlock"] {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    height: 100% !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: flex-start !important;
    overflow: hidden !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > :has(> [data-testid="stVerticalBlock"]) > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
    flex: 0 0 auto !important;
    height: auto !important;
    display: flex !important;
    flex-direction: column !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > :has(> [data-testid="stVerticalBlock"]) > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:last-child {
    margin-top: auto !important;
    flex-shrink: 0 !important;
}
/* Nav block: natural height only; offset below logo/header divider */
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"][data-testid="stVerticalBlock"] {
    flex: 0 0 auto !important;
    height: auto !important;
    margin-top: 0 !important;
    padding-top: 16px !important;
}
/* Footer block: natural height; layout wrapper margin-top:auto anchors it */
section[data-testid="stSidebar"] [class*="st-key-il_rail_footer"][data-testid="stVerticalBlock"] {
    flex: 0 0 auto !important;
    flex-shrink: 0 !important;
    height: auto !important;
    overflow: visible !important;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"],
section[data-testid="stSidebar"] [data-testid="element-container"] {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    width: 100% !important;
    text-align: left !important;
    flex: 0 0 auto !important;
}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] div {
    text-align: left !important;
    color: #C3CED8 !important;
    margin: 0 !important;
}
.il-rail-group {
    font-size: 15px !important;
    font-weight: 700 !important;
    letter-spacing: 0.6px !important;
    line-height: 20px !important;
    text-transform: uppercase;
    color: #6B7F91 !important;
    margin: 0 0 6px 0 !important;
    padding: 0 2px !important;
    text-align: left !important;
}
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="stElementContainer"]:has(.il-rail-group),
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="element-container"]:has(.il-rail-group) {
    margin-bottom: 6px !important;
}
/* Compact separation between REFERENCE (and later groups) and prior nav items */
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="stElementContainer"]:has(.il-rail-group) ~ [data-testid="stElementContainer"]:has(.il-rail-group),
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="element-container"]:has(.il-rail-group) ~ [data-testid="element-container"]:has(.il-rail-group) {
    margin-top: 14px !important;
}
.il-rail-footer {
    margin: 0 !important;
    padding: 16px 8px 0 8px !important;
    border-top: 1px solid rgba(255,255,255,0.08);
    width: 100%;
    box-sizing: border-box;
    flex-shrink: 0;
    overflow: visible !important;
}
.il-rail-user {
    margin: 0 !important;
    padding: 0 !important;
    border-top: none;
    font-size: 12px;
    color: #93a5b6;
    text-align: left !important;
    width: 100%;
    flex-shrink: 0;
    overflow: visible !important;
}
.il-rail-user-main {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 12px;
    text-align: left;
}
.il-rail-user-text {
    min-width: 0;
    text-align: left !important;
}
.il-rail-user .il-avatar-sm {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: #33475b;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 12px;
    border: 1px solid rgba(255,255,255,.15);
    flex-shrink: 0;
}
.il-rail-user .name {
    color: #eaf1f6 !important;
    font-weight: 600;
    font-size: 13px;
    margin-bottom: 0;
    text-align: left !important;
    line-height: 1.3;
}
.il-rail-user .email {
    color: #8ea3b5 !important;
    font-size: 12px;
    margin-top: 2px;
    text-align: left !important;
    line-height: 1.3;
}
.il-rail-user .role {
    color: #8ea3b5 !important;
    font-size: 12px;
    margin-top: 2px;
    text-align: left !important;
}

/* Nav items — shared 48px row rhythm inside il_rail_nav only */
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] div[data-testid="stButton"] {
    margin: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    text-align: left !important;
    min-height: 48px !important;
    display: flex !important;
    align-items: center !important;
}
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="stElementContainer"]:has(div[data-testid="stButton"]),
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="element-container"]:has(div[data-testid="stButton"]) {
    margin-top: 8px !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="stElementContainer"]:has(.il-rail-group) + [data-testid="stElementContainer"]:has(div[data-testid="stButton"]),
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="element-container"]:has(.il-rail-group) + [data-testid="element-container"]:has(div[data-testid="stButton"]),
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="stElementContainer"]:has(.il-rail-group) + [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"]:has(div[data-testid="stButton"]),
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="element-container"]:has(.il-rail-group) + [data-testid="element-container"]:has(.il-nav-active-flag) + [data-testid="element-container"]:has(div[data-testid="stButton"]) {
    margin-top: 0 !important;
}
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"],
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="element-container"]:has(.il-nav-active-flag) + [data-testid="element-container"] {
    min-height: 42px !important;
    height: 42px !important;
}
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"] div[data-testid="stButton"],
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] [data-testid="element-container"]:has(.il-nav-active-flag) + [data-testid="element-container"] div[data-testid="stButton"] {
    min-height: 42px !important;
    height: 42px !important;
}
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] div[data-testid="stButton"] > button,
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] button[data-testid="baseButton-secondary"],
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] button[data-testid="baseButton-primary"],
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] button[kind="secondary"],
section[data-testid="stSidebar"] [class*="st-key-il_rail_nav"] button[kind="primary"] {
    min-height: 48px !important;
    height: 48px !important;
    max-height: 48px !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] {
    margin: 0 0 2px 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    text-align: left !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button,
section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"],
section[data-testid="stSidebar"] button[data-testid="baseButton-primary"],
section[data-testid="stSidebar"] button[kind="secondary"],
section[data-testid="stSidebar"] button[kind="primary"] {
    width: 100% !important;
    max-width: 100% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    text-align: left !important;
    gap: 8px !important;
    background: transparent !important;
    color: #C3CED8 !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0 16px 0 14px !important;
    min-height: 40px !important;
    height: 40px !important;
    max-height: 40px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    box-shadow: none !important;
    position: relative !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    box-sizing: border-box !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div > div {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    text-align: left !important;
    width: 100% !important;
    margin: 0 !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button p,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button span {
    text-align: left !important;
    justify-content: flex-start !important;
    width: auto !important;
    margin: 0 !important;
    flex: 0 1 auto !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
    background: rgba(255,255,255,.05) !important;
    color: #FFFFFF !important;
}
/* Active Overview — 42px, keep red / orange / white */
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"] div[data-testid="stButton"] > button,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-nav-active-flag) + [data-testid="element-container"] div[data-testid="stButton"] > button,
.il-nav-active-flag + div[data-testid="stButton"] > button {
    background: #7F1D1D !important;
    color: #FFFFFF !important;
    box-shadow: none !important;
    min-height: 42px !important;
    height: 42px !important;
    max-height: 42px !important;
    border-radius: 10px !important;
    padding: 0 16px 0 14px !important;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"] div[data-testid="stButton"] > button::before,
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-nav-active-flag) + [data-testid="element-container"] div[data-testid="stButton"] > button::before,
.il-nav-active-flag + div[data-testid="stButton"] > button::before {
    content: "";
    position: absolute;
    left: 0;
    top: 7px;
    bottom: 7px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: #F97316;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag) + [data-testid="stElementContainer"] div[data-testid="stButton"] > button svg,
.il-nav-active-flag + div[data-testid="stButton"] > button svg {
    stroke: #C0392B !important;
    color: #C0392B !important;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-active-flag),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-nav-active-flag),
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.il-nav-badge-slot),
section[data-testid="stSidebar"] [data-testid="element-container"]:has(.il-nav-badge-slot) {
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
}
.il-nav-active-flag { display: none !important; }
.il-nav-badge-slot {
    position: relative;
    height: 0;
    pointer-events: none;
}
.il-nav-badge-slot .il-nav-badge {
    position: absolute;
    right: 16px;
    top: -29px;
}
/* Sign Out: keep horizontal text alignment; compact vertical gap under profile */
section[data-testid="stSidebar"] [class*="st-key-il_rail_footer"] [data-testid="stElementContainer"]:has(.il-rail-footer) + [data-testid="stElementContainer"] div[data-testid="stButton"],
section[data-testid="stSidebar"] [class*="st-key-il_rail_footer"] [data-testid="element-container"]:has(.il-rail-footer) + [data-testid="element-container"] div[data-testid="stButton"],
section[data-testid="stSidebar"] div[class*="st-key-il_sign_out"] div[data-testid="stButton"] {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}
section[data-testid="stSidebar"] [class*="st-key-il_rail_footer"] div[data-testid="stButton"] > button,
section[data-testid="stSidebar"] div[class*="st-key-il_sign_out"] div[data-testid="stButton"] > button {
    min-height: 34px !important;
    height: 34px !important;
    max-height: 34px !important;
    color: #8ea3b5 !important;
    /* Unchanged horizontal alignment with profile name */
    padding: 0 16px 0 56px !important;
    border-radius: 10px !important;
    justify-content: flex-start !important;
}
/* Only normal padding below Sign Out — no large empty region */
section[data-testid="stSidebar"] [class*="st-key-il_rail_footer"][data-testid="stVerticalBlock"] {
    padding-bottom: 11px !important;
}
section[data-testid="stSidebar"] div[class*="st-key-il_sign_out"] {
    padding-bottom: 0 !important;
}

/* —— Main canvas —— */
.stApp [data-testid="stAppViewContainer"] {
    background: var(--canvas) !important;
}
.stApp [data-testid="stAppViewContainer"] > .main {
    margin-top: var(--topbar-h);
    background: var(--canvas) !important;
}
.block-container {
    padding-top: 24px !important;
    padding-bottom: var(--space-page-bottom) !important;
    padding-left: 24px !important;
    padding-right: 24px !important;
    max-width: 1480px !important;
}
/* Tighten Streamlit vertical gaps so header + summary + table fit a laptop viewport */
.stApp [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] {
    margin-bottom: 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] > div {
    gap: var(--space-2) !important;
}

/* Login / user selection — minimal centered User Login */
.il-login-module {
    width: 560px;
    max-width: 90vw;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
}
.il-user-login-icon {
    width: 96px;
    height: 96px;
    border-radius: 50%;
    background: #EEF2F5;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 0 24px 0;
    flex-shrink: 0;
}
.il-user-login-icon svg {
    width: 48px;
    height: 48px;
    display: block;
}
.il-user-login-title {
    margin: 0 0 28px 0 !important;
    font-size: 22px !important;
    font-weight: 700 !important;
    line-height: 1.25 !important;
    color: #1F2B3D !important;
    text-align: center !important;
}

/* —— Typography helpers (shared scale) —— */
.il-type-page {
    font-size: var(--type-page) !important;
    font-weight: var(--weight-page) !important;
    line-height: 1.2;
    letter-spacing: -.3px;
}
.il-type-section {
    font-size: var(--type-section) !important;
    font-weight: var(--weight-section) !important;
    line-height: 1.25;
}
.il-type-card {
    font-size: var(--type-card) !important;
    font-weight: var(--weight-card) !important;
    line-height: 1.3;
    letter-spacing: .02em;
    text-transform: uppercase;
    color: var(--ink-2);
}
.il-type-body { font-size: var(--type-body); line-height: 1.45; color: var(--ink); }
.il-type-caption, .il-caption {
    font-size: var(--type-caption);
    color: var(--ink-2);
    line-height: 1.4;
    font-weight: 500;
}

/* —— Page head —— */
.il-page-head { margin-bottom: var(--space-2); }
.il-page-head h1, .il-page-head .il-type-page {
    font-size: var(--type-page);
    font-weight: var(--weight-page);
    letter-spacing: -.3px;
    color: var(--ink);
    margin: 0;
}
.il-page-head p, .il-page-sub {
    color: var(--ink-2);
    font-size: var(--type-body);
    margin: var(--space-1) 0 0 0;
    max-width: 48rem;
    line-height: 1.4;
}
.il-section-title {
    font-size: var(--type-section);
    font-weight: var(--weight-section);
    color: var(--ink);
    margin: var(--space-3) 0 var(--space-2) 0;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
}
.il-section-title .hint {
    font-size: var(--type-caption);
    color: var(--ink-3);
    font-weight: 500;
}

/* —— KPI strips (compact metrics — not giant story cards) —— */
.il-kpi-row {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: var(--space-2);
    margin-bottom: var(--space-2);
}
.il-kpi-row-compact {
    gap: 14px;
    margin-bottom: var(--space-4);
}
.il-approved-kpi-row {
    grid-template-columns: 1fr 1fr 1fr 1fr 1.18fr !important;
    gap: 14px !important;
    margin-bottom: 18px !important;
    align-items: stretch;
}
.il-kpi {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 8px 10px;
    box-shadow: none;
    min-width: 0;
}
.il-kpi-compact {
    padding: 12px 14px;
    border-radius: 8px;
    height: 128px;
    max-height: 135px;
    min-height: 120px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    overflow: hidden;
}
.il-kpi-compact .lab {
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
    line-height: 1.2;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    max-height: calc(1.2em * 2);
}
.il-kpi-compact .sub {
    font-size: 12px;
    color: var(--ink-3);
    line-height: 1.2;
    margin-top: 4px;
}
.il-kpi .lab {
    font-size: 12px;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: .3px;
    font-weight: var(--weight-card);
    margin-bottom: 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 0 0 auto;
}
.il-kpi .val {
    font-size: 28px;
    font-weight: var(--weight-kpi);
    letter-spacing: -.3px;
    line-height: 1.15;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
}
.il-kpi-compact .val { font-size: 28px; }
.il-kpi-text .val {
    font-size: 16px !important;
    font-weight: 600;
    line-height: 1.3;
    letter-spacing: 0;
    white-space: normal;
}
.il-kpi .sub {
    font-size: 14px;
    margin-top: 2px;
    color: var(--ink-2);
    line-height: 1.3;
    white-space: normal;
}
.il-kpi-text .sub {
    font-size: 14px;
    color: var(--ink);
    font-weight: 500;
}
.il-kpi.accent {
    background: linear-gradient(135deg, var(--brand), var(--brand-dark));
    border: none;
    color: #fff;
}
.il-kpi.accent .lab { color: rgba(255,255,255,.85); }
.il-kpi.accent .val { color: #fff; }
.il-kpi.accent .sub { color: rgba(255,255,255,.9); }
/* Kill stray Streamlit chrome / focus bars inside KPI markdown */
.il-kpi-row [data-testid="stMarkdownContainer"] a,
.il-approved-kpi-row a,
.il-kpi::before,
.il-kpi::after {
    display: none !important;
}

.il-status-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--space-2);
    margin: 0 0 var(--space-2) 0;
    padding: 8px 12px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 8px;
}
.il-status-item { min-width: 0; }
.il-status-item .lab {
    display: block;
    font-size: var(--type-caption);
    color: var(--ink-3);
    font-weight: var(--weight-card);
    margin-bottom: 2px;
    text-transform: uppercase;
    letter-spacing: .3px;
}
.il-status-item .val {
    font-size: var(--type-body);
    font-weight: 600;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.il-agent-brief {
    font-size: var(--type-body);
    line-height: 1.5;
    color: var(--ink);
    margin: 0;
}
.il-first-run-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 10px;
    margin: 0 0 var(--space-2) 0;
    font-size: var(--type-caption);
    color: var(--ink-2);
}
.il-first-run-meta .sep { color: var(--ink-3); }
.il-first-run-meta b { color: var(--ink); font-weight: 600; }
/* Overview operational landing (Queue density) */
.il-overview-greeting {
    font-size: 28px !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
    color: var(--navy) !important;
    margin: 14px 0 8px 0 !important;
}
.il-overview-section {
    font-size: 20px !important;
    font-weight: 650 !important;
    line-height: 1.25 !important;
    color: var(--ink) !important;
    margin: 4px 0 8px 0 !important;
}
.il-overview-healthy {
    margin: 4px 0 8px 0;
    max-width: 640px;
}
.il-overview-healthy-title {
    font-size: 20px !important;
    font-weight: 650 !important;
    margin: 0 0 6px 0 !important;
    color: var(--ink) !important;
}
.il-overview-healthy-body {
    font-size: 15px !important;
    margin: 0 0 4px 0 !important;
    color: var(--ink) !important;
    line-height: 1.4 !important;
}
.il-overview-healthy-monitor {
    font-size: 15px !important;
    margin: 0 0 8px 0 !important;
    color: var(--ink-2) !important;
    line-height: 1.4 !important;
}
.il-overview-healthy-secondary {
    font-size: 12px !important;
    margin: 0 !important;
    color: var(--ink-3) !important;
    line-height: 1.35 !important;
}
.il-overview-priorities .il-queue-head,
.il-overview-priorities .il-queue-row {
    grid-template-columns: 0.55fr 1.35fr 1fr 1.45fr 0.75fr 0.75fr 1.2fr 0.1fr;
    gap: 6px;
    padding: 5px 4px;
    font-size: 14px;
}



/* —— Decision dashboard tiles (Overview) —— */
.il-dash-tiles {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
    align-items: stretch;
    width: 100%;
    margin-top: 20px;
    margin-bottom: 16px;
}
.il-dash-tiles-anchor {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Collapse Streamlit element chrome so intro → cards spacing stays ~20px */
div[data-testid="stElementContainer"]:has(.il-overview-lede),
div[data-testid="element-container"]:has(.il-overview-lede) {
    margin-bottom: 0 !important;
    padding-bottom: 0 !important;
}
div[data-testid="stElementContainer"]:has(.il-dash-tiles-anchor),
div[data-testid="element-container"]:has(.il-dash-tiles-anchor) {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Four-card row in normal document flow */
div[data-testid="stHorizontalBlock"]:has(.il-dash-tile-wrap) {
    gap: 16px !important;
    width: 100% !important;
    margin: 20px 0 12px 0 !important;
    padding: 0 !important;
}
div[data-testid="column"]:has(.il-dash-tile-wrap) {
    position: relative !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
div[data-testid="column"]:has(.il-dash-tile-wrap) [data-testid="stElementContainer"]:has(.il-dash-tile-wrap) {
    margin: 0 !important;
    padding: 0 !important;
    /* Face container must not intercept clicks meant for the button underneath */
    pointer-events: none !important;
}
/*
 * Real click target = st.button (in flow, 180px).
 * HTML card face is painted over it with pointer-events:none so clicks always
 * reach Streamlit. Do not use absolute overlays that can miss the hit area.
 */
div[class*="st-key-dash_tile_nav_"] {
    position: relative !important;
    height: 180px !important;
    max-height: 180px !important;
    min-height: 180px !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 1 !important;
}
div[class*="st-key-dash_tile_nav_"] div[data-testid="stButton"] {
    margin: 0 !important;
    height: 180px !important;
}
div[class*="st-key-dash_tile_nav_"] div[data-testid="stButton"] > button {
    height: 180px !important;
    min-height: 180px !important;
    width: 100% !important;
    opacity: 0 !important;
    cursor: pointer !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    color: transparent !important;
    pointer-events: auto !important;
}
/* Decorative face: pull over the button; never capture clicks */
.il-dash-tile-wrap {
    width: 100%;
    margin: -180px 0 0 0 !important;
    padding: 0 !important;
    position: relative !important;
    z-index: 2 !important;
    pointer-events: none !important;
}
.il-dash-tile {
    display: block;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 24px;
    position: relative;
    overflow: hidden;
    height: 180px;
    min-height: 180px;
    max-height: 180px;
    box-sizing: border-box;
    text-decoration: none !important;
    color: inherit !important;
    cursor: pointer;
    pointer-events: none !important;
    transition: box-shadow 160ms ease, border-color 160ms ease;
}
div[data-testid="column"]:has(.il-dash-tile-wrap):hover .il-dash-tile,
div[data-testid="column"]:has(div[class*="st-key-dash_tile_nav_"]:hover) .il-dash-tile {
    box-shadow: var(--shadow-hover, 0 6px 18px rgba(15, 23, 42, 0.10));
    border-color: #94A3B8;
}
div[data-testid="column"]:has(.il-dash-tile-wrap):focus-within .il-dash-tile {
    outline: 2px solid #2563EB;
    outline-offset: 2px;
}
/* Suppress Streamlit help/tooltip "Close" affordance on card nav */
div[class*="st-key-dash_tile_nav_"] [data-testid="stTooltipIcon"],
div[class*="st-key-dash_tile_nav_"] [data-testid="stTooltipHoverTarget"],
div[class*="st-key-dash_tile_nav_"] [data-testid="stTooltipContent"],
div[data-testid="column"]:has(.il-dash-tile-wrap) [data-testid="stTooltipIcon"],
div[data-testid="column"]:has(.il-dash-tile-wrap) [data-testid="stTooltipHoverTarget"] {
    display: none !important;
}
/* Suppress stray tooltip Close chrome in the main Overview surface */
section.main [data-testid="stTooltipContent"],
section.main [data-baseweb="tooltip"] {
    display: none !important;
}
.il-dash-tile::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
}
.il-dash-tile.accent-danger::before { background: var(--danger); }
.il-dash-tile.accent-amber::before { background: var(--amber); }
.il-dash-tile.accent-success::before { background: var(--green); }
.il-dash-tile.accent-info::before { background: #2563EB; }
.il-dash-tile .lab {
    display: block;
    font-size: 12px;
    font-weight: 650;
    letter-spacing: .05em;
    text-transform: uppercase;
    color: #6B7C8F;
    margin: 0 0 10px 0;
    line-height: 1.2;
    padding-right: 20px;
}
.il-dash-tile .val {
    display: block;
    font-size: 32px;
    font-weight: 700;
    line-height: 1.1;
    color: var(--navy);
    font-variant-numeric: tabular-nums;
    margin: 0 0 10px 0;
}
.il-dash-tile .exp {
    font-size: 14px;
    color: var(--ink-2);
    margin: 0;
    line-height: 1.35;
    padding-right: 20px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.il-dash-tile .chev {
    position: absolute;
    right: 16px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 22px;
    color: #9CA3AF;
    font-weight: 400;
    transition: transform 160ms ease, color 160ms ease;
}
div[data-testid="column"]:has(.il-dash-tile-wrap):hover .il-dash-tile .chev {
    color: var(--ink);
    transform: translateY(-50%) translateX(3px);
}
.il-dash-toolbar {
    margin: 0;
}
.il-dash-toolbar-anchor {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Compact spacing: cards → filters (~16–20px) and filters → table (~16–20px) */
div[data-testid="stHorizontalBlock"]:has(.il-dash-tile-wrap) {
    margin: 20px 0 18px 0 !important;
}
div:has(> .il-dash-toolbar-anchor) + div [data-testid="stHorizontalBlock"],
div:has(.il-dash-toolbar-anchor) ~ div [data-testid="stHorizontalBlock"]:has(.il-dash-filter-group) {
    margin: 0 0 18px 0 !important;
    gap: 12px !important;
    align-items: center !important;
}
div:has(> .il-dash-toolbar-anchor) + div [data-testid="stHorizontalBlock"] [data-testid="stButton"] > button,
div:has(.il-dash-toolbar-anchor) ~ div [data-testid="stHorizontalBlock"] [data-testid="stButton"] > button,
div[data-testid="stHorizontalBlock"]:has(.il-dash-filter-group) [data-testid="stButton"] > button,
div[data-testid="stHorizontalBlock"]:has(.il-dash-action-group) [data-testid="stButton"] > button {
    min-height: 40px !important;
    height: 40px !important;
    max-height: 40px !important;
    font-size: 13px !important;
    border-radius: 8px !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    white-space: nowrap !important;
    line-height: 1.2 !important;
}
.il-dash-toolbar [data-testid="stButton"] > button {
    min-height: 40px !important;
    height: 40px !important;
    font-size: 13px !important;
    border-radius: 8px !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    white-space: nowrap !important;
}
/* One continuous Replenishment Decisions card */
.il-dash-panel {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 0;
    margin: 0 0 12px 0;
    overflow: hidden;
}
.il-dash-panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 52px;
    padding: 0 18px;
    border-bottom: 1px solid var(--line);
}
.il-dash-panel-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--navy);
}
.il-dash-panel-sub {
    font-size: 12px;
    color: var(--ink-3);
}
.il-dash-panel-body {
    display: block;
    width: 100%;
    box-sizing: border-box;
    padding: 20px 16px;
}
.il-dash-panel-body--table {
    display: block;
    padding: 0 0 8px 0;
}
.il-dash-filter-group,
.il-dash-action-group {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
div[data-testid="stHorizontalBlock"]:has(.il-dash-filter-group),
div[data-testid="stHorizontalBlock"]:has(.il-dash-action-group) {
    gap: 12px !important;
    align-items: center !important;
}
/* Shared header/body grid — exact same columns (wins over generic .il-queue-row) */
.il-dash-table .il-queue-head,
.il-dash-table .il-queue-row,
.il-dash-panel .il-dash-table .il-queue-head,
.il-dash-panel .il-dash-table .il-queue-row {
    display: grid !important;
    grid-template-columns:
        1.35fr
        1.00fr
        1.15fr
        0.82fr
        1.03fr
        0.68fr
        1.05fr
        1.10fr !important;
    align-items: center;
    justify-items: stretch;
    gap: 0 12px !important;
    column-gap: 12px !important;
    row-gap: 0 !important;
    margin: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    border-left: none !important;
    border-right: none !important;
    border-top: none !important;
    min-height: 0 !important;
    height: auto !important;
    max-height: none !important;
    padding-left: 24px !important;
    padding-right: 24px !important;
    box-sizing: border-box !important;
}
.il-dash-table .il-queue-head {
    min-height: 0 !important;
    padding-top: 14px !important;
    padding-bottom: 14px !important;
    border-bottom: 1px solid #E6EBF1;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 11px;
    font-weight: 650;
    color: var(--ink-3, #6B7C8F);
}
.il-dash-table .il-queue-row {
    background: var(--card);
    border-bottom: 1px solid #E6EBF1;
    cursor: pointer;
    min-height: 0 !important;
    height: auto !important;
    padding-top: 12px !important;
    padding-bottom: 12px !important;
}
.il-dash-table .il-queue-head .il-demand-head,
.il-dash-table .il-queue-head > div:nth-child(4) {
    white-space: nowrap;
    text-align: right;
}
.il-dash-table .il-queue-head > div:nth-child(1),
.il-dash-table .il-queue-head > div:nth-child(2),
.il-dash-table .il-queue-head > div:nth-child(3),
.il-dash-table .il-queue-head > div:nth-child(5),
.il-dash-table .il-queue-head > div:nth-child(7),
.il-dash-table .il-queue-head > div:nth-child(8) {
    text-align: left;
}
.il-dash-table .il-queue-head > div:nth-child(6) {
    text-align: right;
}
.il-dash-table .il-queue-row.is-last,
.il-dash-table .il-queue-row:last-child {
    border-bottom: 1px solid #E6EBF1;
}
.il-dash-table .il-queue-row:hover {
    background: #F7F9FC;
}
.il-dash-panel .il-dash-table,
div[class*="st-key-dash_decisions_wrap"] .il-dash-table {
    padding: 0 !important;
    margin: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}
/* Same content width for header markdown and each row hit container */
div[class*="st-key-dash_decisions_wrap"] [data-testid="stElementContainer"],
div[class*="st-key-dash_row_hit_"] [data-testid="stElementContainer"] {
    padding-left: 0 !important;
    padding-right: 0 !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
}
div[class*="st-key-dash_row_hit_"] {
    position: relative !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
}
/* Compact cell treatments — Overview decisions table only */
.il-dash-table .il-item-cell,
.il-dash-table .il-store-cell,
.il-dash-table .il-exception-wrap,
.il-dash-table .il-dos-wrap {
    text-align: left;
    margin: 0;
    padding: 0;
}
.il-dash-table .il-item-cell .name {
    font-weight: 600;
    color: var(--ink);
    display: block;
    margin: 0 0 2px 0;
    line-height: 1.25;
}
.il-dash-table .il-item-cell .sku {
    font-size: 12px;
    color: var(--ink-3);
    display: block;
    margin: 0;
    line-height: 1.2;
}
.il-dash-table .il-store-cell {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
}
.il-dash-table .il-exception-wrap,
.il-dash-table .il-exception-cell {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    gap: 0;
    min-width: 0;
}
.il-dash-table .il-review-reason {
    font-size: 13px;
    line-height: 1.25;
    font-weight: 400;
    color: var(--ink-3, #6B7C8F);
    margin-top: 3px;
    max-width: 100%;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.il-dash-table .il-demand-cell.num,
.il-dash-table .il-queue-head .num,
.il-dash-table .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    margin: 0;
    padding: 0;
}
.il-dash-table .il-qty {
    text-align: right;
    font-weight: 600;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    margin: 0;
    padding: 0;
}
.il-dash-table .il-dos-wrap,
.il-dash-table .il-dos {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 8px;
    min-width: 0;
    white-space: nowrap;
}
.il-dash-table .il-dos-track {
    flex: 0 0 96px;
    width: 96px;
    min-width: 96px;
    max-width: 96px;
    height: 6px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
}
.il-dash-table .il-dos-val {
    font-size: 13px;
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
    min-width: 2.5rem;
}
.il-dash-table .il-conf-wrap,
.il-dash-table .il-conf {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 6px;
    min-width: 0;
    width: 100%;
    white-space: nowrap;
    font-size: 12px;
    color: var(--ink-2);
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}
.il-dash-table .il-conf-track {
    flex: 0 0 96px;
    width: 96px;
    min-width: 96px;
    max-width: 96px;
    height: 5px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
}
.il-dash-table .il-conf > span {
    flex: 0 0 auto;
    white-space: nowrap;
}
.il-dash-table .il-status-cell {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    min-width: 0;
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    white-space: nowrap;
}
.il-dash-table .il-status-cell .il-pill,
.il-dash-table .il-status-cell span {
    white-space: nowrap;
}
/* Decisions card: wrap owns chrome; rows use tile-style button-under-face hits */
div[class*="st-key-dash_decisions_wrap"] {
    position: relative !important;
    background: var(--card) !important;
    border: 1px solid var(--line) !important;
    border-radius: 14px !important;
    box-shadow: var(--shadow) !important;
    overflow: hidden !important;
    margin: 0 0 12px 0 !important;
    padding-bottom: 10px !important;
}
div[class*="st-key-dash_decisions_wrap"] .il-dash-panel {
    border: none !important;
    box-shadow: none !important;
    margin: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
}
/* Per-row hit: face owns content height; transparent button fills the row */
div[class*="st-key-dash_row_hit_"] {
    position: relative !important;
}
div[class*="st-key-dash_row_nav_"] {
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    top: 0 !important;
    bottom: 0 !important;
    height: auto !important;
    max-height: none !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 1 !important;
}
div[class*="st-key-dash_row_nav_"] div[data-testid="stButton"] {
    margin: 0 !important;
    height: 100% !important;
}
div[class*="st-key-dash_row_nav_"] div[data-testid="stButton"] > button,
div[class*="st-key-dash_row_nav_"] div[data-testid="stButton"] > button:hover,
div[class*="st-key-dash_row_nav_"] div[data-testid="stButton"] > button:focus,
div[class*="st-key-dash_row_nav_"] div[data-testid="stButton"] > button:active {
    height: 100% !important;
    min-height: 100% !important;
    width: 100% !important;
    opacity: 0 !important;
    cursor: pointer !important;
    border: none !important;
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: none !important;
    color: transparent !important;
    pointer-events: auto !important;
}
/* Face in normal flow — defines row height; clicks pass through to the button */
div[class*="st-key-dash_row_hit_"] [data-testid="stElementContainer"]:has(.il-dash-row) {
    margin: 0 !important;
    padding: 0 !important;
    position: relative !important;
    z-index: 2 !important;
    pointer-events: none !important;
}
div[class*="st-key-dash_row_hit_"] .il-dash-table,
div[class*="st-key-dash_row_hit_"] .il-queue-row {
    pointer-events: none !important;
}
div[class*="st-key-dash_row_hit_"]:hover .il-queue-row,
div[class*="st-key-dash_row_hit_"]:has(div[class*="st-key-dash_row_nav_"]:hover) .il-queue-row {
    background: #F7F9FC !important;
}
div[data-testid="stElementContainer"]:has(.il-dash-panel) {
    margin-bottom: 0 !important;
}
.il-dash-empty {
    font-size: 15px;
    color: var(--ink-2);
    padding: 12px 4px 16px;
    margin: 0;
}
.il-dash-zero {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 24px;
    margin: 0;
    width: 100%;
}
.il-dash-zero-icon {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    background: var(--subtle);
    border: 1px solid var(--line);
    color: #9CA3AF;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    margin-bottom: 12px;
    position: relative;
}
.il-dash-zero-icon::before {
    content: "";
    width: 16px;
    height: 14px;
    border: 2px solid #9CA3AF;
    border-radius: 2px;
    box-sizing: border-box;
}
.il-dash-zero-title {
    font-size: 15px;
    font-weight: 650;
    color: var(--ink);
    margin: 0 0 6px 0;
}
.il-dash-zero-sub {
    font-size: 13px;
    color: var(--ink-3);
    margin: 0;
    max-width: 420px;
    line-height: 1.4;
}
/* Keep one shared grid — do not redefine columns here */
.il-dash-panel .il-dash-table {
    padding: 0;
    width: 100%;
}
.il-conf {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--ink-2);
}
.il-conf-track {
    flex: 1;
    height: 5px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
    min-width: 36px;
}
.il-conf-fill {
    height: 100%;
    border-radius: 999px;
    background: #2563EB;
}
.il-conf-na { font-size: 12px; color: var(--ink-3); }

/* —— Expected deliveries tiles + side panel —— */
.il-del-tile {
    background: #FFFFFF;
    border: 1px solid #DCE3EA;
    border-radius: 12px;
    padding: 18px 20px;
    margin: 0;
    box-sizing: border-box;
    transition: border-color 160ms ease;
}
.il-del-tile.is-selected {
    background: #FFFFFF;
    border-color: #93C5FD;
}
.il-del-tile-main {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
}
.il-del-po {
    font-size: 16px;
    font-weight: 700;
    color: var(--ink, #111827);
    line-height: 1.3;
}
.il-del-product {
    font-size: 14px;
    font-weight: 500;
    color: #4B5563;
    margin-top: 4px;
    line-height: 1.35;
}
.il-del-tile-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
    flex-shrink: 0;
    position: relative;
    padding-right: 18px;
}
.il-del-date {
    font-size: 12px;
    color: #9CA3AF;
    line-height: 1.3;
}
.il-del-chev {
    position: absolute;
    right: 0;
    top: 50%;
    transform: translateY(-50%);
    font-size: 22px;
    color: #9CA3AF;
    line-height: 1;
    font-weight: 300;
}
.il-del-badge {
    display: inline-flex;
    align-items: center;
    border-radius: 999px;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.2;
    white-space: nowrap;
}
.il-del-badge--placed {
    background: var(--status-success-bg, #dcfce7);
    color: var(--status-success, #15803d);
}
.il-del-badge--transit {
    background: var(--status-progress-bg, #dbeafe);
    color: var(--status-progress, #1d4ed8);
}
.il-del-badge--delivered {
    background: #f3e8ff;
    color: #7e22ce;
}
.il-del-tracker {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin: 18px auto 0;
    max-width: 520px;
    width: 100%;
    position: relative;
}
.il-del-tracker::before {
    content: "";
    position: absolute;
    left: 16.5%;
    right: 16.5%;
    top: 7px;
    height: 2px;
    background: #E5E7EB;
    z-index: 0;
}
.il-del-step {
    position: relative;
    z-index: 1;
    text-align: center;
}
.il-del-step-marker {
    display: flex;
    justify-content: center;
    margin-bottom: 8px;
}
.il-del-step .dot {
    width: 14px;
    height: 14px;
    border-radius: 999px;
    background: #FFFFFF;
    border: 2px solid #D1D5DB;
    box-sizing: border-box;
    display: inline-block;
}
.il-del-step.is-done .dot,
.il-del-step.is-active .dot {
    background: #2563EB;
    border-color: #2563EB;
}
.il-del-step-lab {
    font-size: 12px;
    font-weight: 600;
    color: var(--ink-2, #4B5563);
    line-height: 1.25;
}
.il-del-step.is-todo .il-del-step-lab {
    color: #9CA3AF;
    font-weight: 500;
}
.il-del-step-date {
    font-size: 11px;
    color: #9CA3AF;
    margin-top: 2px;
    line-height: 1.25;
}
.il-del-tracker.compact {
    margin-top: 16px;
    max-width: 460px;
}

/* Transparent full-tile click target (Overview row pattern) */
div[class*="st-key-delivery_hit_"] {
    position: relative !important;
    margin: 0 0 10px 0 !important;
}
div[class*="st-key-delivery_card_"] {
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    top: 0 !important;
    bottom: 0 !important;
    height: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 1 !important;
}
div[class*="st-key-delivery_card_"] div[data-testid="stButton"] {
    margin: 0 !important;
    height: 100% !important;
}
div[class*="st-key-delivery_card_"] div[data-testid="stButton"] > button,
div[class*="st-key-delivery_card_"] div[data-testid="stButton"] > button:hover,
div[class*="st-key-delivery_card_"] div[data-testid="stButton"] > button:focus,
div[class*="st-key-delivery_card_"] div[data-testid="stButton"] > button:active {
    height: 100% !important;
    min-height: 100% !important;
    width: 100% !important;
    opacity: 0 !important;
    cursor: pointer !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    color: transparent !important;
}
div[class*="st-key-delivery_hit_"] [data-testid="stElementContainer"]:has(.il-del-tile) {
    margin: 0 !important;
    padding: 0 !important;
    position: relative !important;
    z-index: 2 !important;
    pointer-events: none !important;
}
div[class*="st-key-delivery_hit_"] .il-del-tile {
    pointer-events: none !important;
}
div[class*="st-key-delivery_hit_"]:hover .il-del-tile,
div[class*="st-key-delivery_hit_"]:has(div[class*="st-key-delivery_card_"]:hover) .il-del-tile {
    border-color: #93C5FD !important;
    background: #FFFFFF !important;
}

/* Side panel — fixed overlay; list stays full-width (no column reflow flash) */
div[data-testid="stElementContainer"]:has(> div[class*="st-key-delivery_side_panel"]),
div[data-testid="element-container"]:has(> div[class*="st-key-delivery_side_panel"]) {
    position: fixed !important;
    top: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: min(42vw, 520px) !important;
    max-width: 100vw !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
    z-index: 1000 !important;
    border: none !important;
    background: transparent !important;
    transition: none !important;
    animation: none !important;
}
div[class*="st-key-delivery_side_panel"] {
    position: fixed !important;
    top: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: min(42vw, 520px) !important;
    max-width: 100vw !important;
    height: 100vh !important;
    z-index: 1000 !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    background: #FFFFFF !important;
    border: none !important;
    border-left: 1px solid #DCE3EA !important;
    border-radius: 0 !important;
    box-shadow: -8px 0 24px rgba(0,0,0,0.08) !important;
    padding: calc(var(--topbar-h, 64px) + 16px) 32px 28px 32px !important;
    margin: 0 !important;
    box-sizing: border-box !important;
    transition: none !important;
    animation: none !important;
}
@media (max-width: 900px) {
    div[data-testid="stElementContainer"]:has(> div[class*="st-key-delivery_side_panel"]),
    div[data-testid="element-container"]:has(> div[class*="st-key-delivery_side_panel"]),
    div[class*="st-key-delivery_side_panel"] {
        width: 100vw !important;
        left: 0 !important;
        right: 0 !important;
    }
}

/* Inventory on Hand — table + side panel */
div[data-testid="stElementContainer"]:has(> div[class*="st-key-inventory_side_panel"]),
div[data-testid="element-container"]:has(> div[class*="st-key-inventory_side_panel"]) {
    position: fixed !important;
    top: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: min(42vw, 520px) !important;
    max-width: 100vw !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
    z-index: 1000 !important;
    border: none !important;
    background: transparent !important;
    transition: none !important;
    animation: none !important;
}
div[class*="st-key-inventory_side_panel"] {
    position: fixed !important;
    top: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: min(42vw, 520px) !important;
    max-width: 100vw !important;
    height: 100vh !important;
    z-index: 1000 !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    background: #FFFFFF !important;
    border: none !important;
    border-left: 1px solid #DCE3EA !important;
    border-radius: 0 !important;
    box-shadow: -8px 0 24px rgba(0,0,0,0.08) !important;
    padding: calc(var(--topbar-h, 64px) + 16px) 32px 28px 32px !important;
    margin: 0 !important;
    box-sizing: border-box !important;
    transition: none !important;
    animation: none !important;
}
@media (max-width: 900px) {
    div[data-testid="stElementContainer"]:has(> div[class*="st-key-inventory_side_panel"]),
    div[data-testid="element-container"]:has(> div[class*="st-key-inventory_side_panel"]),
    div[class*="st-key-inventory_side_panel"] {
        width: 100vw !important;
        left: 0 !important;
        right: 0 !important;
    }
}
.inventory-details-title {
    font-size: 30px;
    font-weight: 700;
    line-height: 1.2;
    color: #111827;
    margin: 0;
}
.il-inv-panel-product {
    font-size: 18px;
    font-weight: 600;
    color: var(--ink);
    margin-top: 12px;
}
.il-inv-panel-sku {
    font-size: 12px;
    color: var(--ink-3);
    margin-bottom: 14px;
}
.il-inv-panel-section {
    margin-top: 18px;
}
.il-inv-panel-section-lab {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .3px;
    color: var(--ink-3);
    margin-bottom: 4px;
}
.il-inv-panel-section-val {
    font-size: 15px;
    color: var(--ink);
    line-height: 1.4;
}
.il-inv-panel-meta {
    font-size: 12px;
    color: var(--ink-3);
    margin-top: 4px;
}
.il-inv-table-head,
.il-inv-table-row {
    display: grid;
    grid-template-columns: 1.6fr 1.15fr 1.15fr 0.85fr 0.85fr 0.95fr 0.95fr;
    gap: 10px;
    align-items: center;
}
.il-inv-table-head {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .3px;
    color: var(--ink-3);
    padding: 0 12px 8px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 4px;
}
.il-inv-table-row {
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid transparent;
    font-size: 14px;
    color: var(--ink);
}
.il-inv-table-row.is-selected {
    background: #f3f6f9;
    border-color: #d7e0ea;
}
.il-inv-cell.num {
    font-variant-numeric: tabular-nums;
    text-align: right;
}
.il-inv-product .name {
    font-weight: 600;
    color: var(--ink);
    line-height: 1.25;
}
.il-inv-product .sku {
    font-size: 11px;
    color: var(--ink-3);
    margin-top: 2px;
}
div[class*="st-key-inv_hit_"] {
    position: relative !important;
    margin: 0 0 2px 0 !important;
}
div[class*="st-key-inv_row_"] {
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    top: 0 !important;
    bottom: 0 !important;
    height: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 1 !important;
}
div[class*="st-key-inv_row_"] div[data-testid="stButton"] {
    margin: 0 !important;
    height: 100% !important;
}
div[class*="st-key-inv_row_"] div[data-testid="stButton"] > button,
div[class*="st-key-inv_row_"] div[data-testid="stButton"] > button:hover,
div[class*="st-key-inv_row_"] div[data-testid="stButton"] > button:focus,
div[class*="st-key-inv_row_"] div[data-testid="stButton"] > button:active {
    height: 100% !important;
    min-height: 100% !important;
    width: 100% !important;
    opacity: 0 !important;
    cursor: pointer !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    color: transparent !important;
}
div[class*="st-key-inv_hit_"] [data-testid="stElementContainer"]:has(.il-inv-table-row) {
    margin: 0 !important;
    padding: 0 !important;
    position: relative !important;
    z-index: 2 !important;
    pointer-events: none !important;
}
div[class*="st-key-inv_hit_"] .il-inv-table-row {
    pointer-events: none !important;
}
@media (max-width: 1100px) {
    .il-inv-table-head,
    .il-inv-table-row {
        grid-template-columns: 1.4fr 1fr 1fr 0.75fr 0.75fr 0.85fr 0.85fr;
        font-size: 13px;
    }
}
.delivery-details-title {
    font-size: 30px;
    font-weight: 700;
    line-height: 1.2;
    color: #111827;
    margin: 0;
}
.il-del-panel-hero {
    margin: 8px 0 18px 0;
}
.il-del-panel-hero .il-del-badge {
    margin-bottom: 10px;
}
.il-del-panel-po {
    font-size: 20px;
    font-weight: 700;
    color: var(--ink, #111827);
    margin-top: 8px;
}
.il-del-panel-product {
    font-size: 14px;
    font-weight: 500;
    color: #4B5563;
    margin-top: 4px;
}
.il-del-panel-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 36px;
    row-gap: 26px;
    margin: 22px 0 8px 0;
}
.il-del-panel-field .lab {
    display: block;
    font-size: 12px;
    font-weight: 500;
    color: #9CA3AF;
}
.il-del-panel-field .val {
    display: block;
    font-size: 15px;
    font-weight: 500;
    color: var(--ink, #111827);
    margin-top: 4px;
    line-height: 1.35;
    word-break: break-word;
}
.il-del-invoice-sep {
    border-top: 1px solid #E5E7EB;
    margin: 22px 0 16px 0;
}
.il-del-invoice-lab {
    font-size: 12px;
    font-weight: 500;
    color: #9CA3AF;
    margin-bottom: 8px;
}
@media (max-width: 900px) {
    .il-del-panel-grid {
        grid-template-columns: 1fr;
        row-gap: 18px;
    }
}
@media (max-width: 1100px) {
    .il-dash-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
}
@media (max-width: 700px) {
    .il-dash-tiles { grid-template-columns: 1fr !important; }
}

/* —— Enterprise dashboard (Overview) —— */
.il-ent-summary {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 14px;
    margin: 12px 0 16px 0;
}
.il-ent-card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow);
    padding: 14px 16px 14px 18px;
    position: relative;
    overflow: hidden;
    transition: box-shadow var(--transition, 200ms ease), transform var(--transition, 200ms ease);
    min-height: 110px;
    max-height: 140px;
}
.il-ent-card:hover { box-shadow: var(--shadow-hover); transform: translateY(-1px); }
.il-ent-card::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
}
.il-ent-card.accent-danger::before { background: var(--danger); }
.il-ent-card.accent-amber::before { background: var(--amber); }
.il-ent-card.accent-success::before { background: var(--green); }
.il-ent-card.accent-info::before { background: #2563EB; }
.il-ent-card .lab {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: var(--ink-3);
    margin: 0 0 6px 0;
}
.il-ent-card .val {
    font-size: 28px;
    font-weight: 700;
    line-height: 1.15;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
}
.il-ent-card .sub {
    font-size: 12px;
    color: var(--ink-2);
    margin-top: 6px;
    line-height: 1.3;
}
.il-overview-greeting {
    font-size: 28px !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
    color: var(--navy) !important;
    margin: 14px 0 8px 0 !important;
}
.il-overview-lede {
    font-size: 15px !important;
    font-weight: 400 !important;
    color: var(--ink-2) !important;
    margin: 0 0 0 0 !important;
    line-height: 1.45 !important;
    max-width: none !important;
}
.il-ent-panel {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow);
    padding: 14px 16px 8px 16px;
    margin-bottom: 12px;
}
.il-ent-panel-title {
    font-size: 20px;
    font-weight: 650;
    margin: 0 0 2px 0;
    color: var(--ink);
}
.il-ent-panel-sub {
    font-size: 12px;
    color: var(--ink-3);
    margin: 0 0 10px 0;
}
.il-ent-table .il-queue-head,
.il-ent-table .il-queue-row {
    grid-template-columns: 1.55fr 1fr 1.2fr 0.8fr 1.1fr 0.9fr 0.9fr;
    gap: 8px;
    min-height: var(--row-h);
    padding: 10px 6px;
    transition: background var(--transition, 200ms ease);
}
.il-ent-table .il-queue-row:hover { background: var(--hover); }
.il-item-cell .name { font-weight: 600; color: var(--ink); display: block; }
.il-item-cell .sku { font-size: 12px; color: var(--ink-3); display: block; margin-top: 2px; }
.il-exception-cell { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
.il-review-reason {
    font-size: 12px;
    line-height: 1.35;
    color: var(--ink-3, #6B7C8F);
    max-width: 220px;
}
.il-qty { font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; }
.il-dos {
    display: flex;
    align-items: center;
    gap: 8px;
}
.il-dos-track {
    flex: 1;
    height: 6px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
    min-width: 48px;
}
.il-dos-fill {
    height: 100%;
    border-radius: 999px;
    transition: width var(--transition, 200ms ease);
}
.il-dos-fill.ok { background: var(--green); }
.il-dos-fill.warn { background: var(--amber); }
.il-dos-fill.crit { background: var(--danger); }
.il-dos-val { font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums; min-width: 2.5rem; }
.il-empty-success {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow);
    padding: 36px 24px 28px;
    text-align: center;
    max-width: 760px;
    margin: 8px auto 18px auto;
}
.il-empty-success .check {
    width: 56px; height: 56px; border-radius: 50%;
    background: var(--status-success-bg);
    color: var(--green);
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 28px; font-weight: 700; margin-bottom: 12px;
}
.il-empty-success h2 {
    font-size: 20px; font-weight: 650; margin: 0 0 6px 0; color: var(--ink);
}
.il-empty-success p.body {
    font-size: 15px; color: var(--ink-2); margin: 0 auto 18px auto; max-width: 420px;
}
.il-empty-mini {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin-top: 8px;
    text-align: left;
}
.il-empty-mini .mini {
    background: var(--subtle);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 10px 12px;
}
.il-empty-mini .mini .lab { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-3); font-weight: 600; }
.il-empty-mini .mini .val { font-size: 14px; font-weight: 600; color: var(--ink); margin-top: 4px; }
.il-nav-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 18px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    background: rgba(255,255,255,.12);
    color: #E5E7EB;
}
.il-nav-badge.hot {
    background: #DC2626;
    color: #fff;
}
@media (max-width: 1100px) {
    .il-ent-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .il-empty-mini { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
    .il-ent-summary { grid-template-columns: 1fr; }
    .il-empty-mini { grid-template-columns: 1fr; }
}

/* Legacy CMO briefing styles (unused on Overview) */
.il-cmo-headline { font-size: 28px !important; font-weight: 600 !important; }
/* Keep page content below the fixed topbar stacking context (no caption bleed). */
section.main > div,
div[data-testid="stAppViewContainer"] > .main {
    position: relative;
    z-index: 0;
}
.il-kpi-compact-inline .val {
    font-size: var(--type-kpi);
    font-weight: var(--weight-kpi);
    color: var(--ink);
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
}
.il-kpi-compact-inline .lab {
    font-size: var(--type-body);
    color: var(--ink);
    margin: 4px 0 2px 0;
}
.il-kpi-compact-inline .il-caption { margin: 0; }
.il-handled-list {
    margin: 0;
    padding-left: 1.1rem;
    font-size: var(--type-body);
    color: var(--ink);
}
.il-handled-list li { margin: 4px 0; }
.il-data-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}
.il-data-chip {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--subtle);
}
.il-data-chip .lab {
    font-size: var(--type-caption);
    font-weight: 600;
    color: var(--ink-2);
}
.il-overview-attention .il-queue-head,
.il-overview-attention .il-queue-row {
    grid-template-columns: 0.7fr 1fr 1.4fr 0.7fr 1.2fr 1fr 0.8fr 0.2fr;
}
.il-approved-table .il-queue-head,
.il-approved-table .il-queue-row {
    display: grid !important;
    grid-template-columns:
        1.20fr
        1.85fr
        0.75fr
        0.78fr
        1.30fr
        1.25fr
        1.40fr !important;
    column-gap: 14px !important;
    gap: 0 14px !important;
    align-items: center;
    padding-top: 12px !important;
    padding-bottom: 12px !important;
    min-height: 0 !important;
}
.il-approved-table .il-queue-head {
    padding-top: 8px !important;
    padding-bottom: 8px !important;
}
.il-approved-table .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.il-approved-table .il-approved-nowrap {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
[class*="st-key-approved_decisions_panel"] .il-section-title {
    font-size: 20px !important;
    font-weight: 600 !important;
    margin: 0 0 12px 0 !important;
    text-transform: none !important;
    letter-spacing: normal !important;
    color: var(--ink) !important;
}
[class*="st-key-approved_decisions_panel"] [data-testid="stExpander"] {
    margin-top: 16px !important;
}
[class*="st-key-approved_decisions_panel"] {
    margin-top: 4px !important;
}
.il-orders-table .il-queue-head,
.il-orders-table .il-queue-row {
    grid-template-columns: minmax(200px, 2.15fr) 1.5fr 0.5fr 0.4fr 0.55fr 1.05fr 0.75fr 1.5fr 1.3fr;
    align-items: start;
}
.il-orders-table .il-po-id {
    overflow-wrap: break-word;
    word-break: normal;
    line-height: 1.3;
    font-variant-numeric: tabular-nums;
}
.il-orders-table .il-queue-row.is-selected,
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"].is-selected {
    background: transparent;
}
.il-po-select-prompt {
    margin-top: 14px;
    margin-bottom: 8px;
    color: var(--ink-2);
}
[class*="st-key-il_orders_card"] {
    max-width: 100% !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
    container-type: inline-size;
    container-name: orders-card;
}
[class*="st-key-il_orders_card"] .il-panel-title {
    margin-bottom: 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-il_orders_card"]) > div {
    gap: 0 !important;
}
[class*="st-key-orders_table_grid"] {
    --orders-grid-cols: 1.45fr 1.45fr 1.25fr 0.55fr 0.65fr 1.45fr minmax(155px, 1.35fr) minmax(105px, 1.15fr) minmax(95px, 1.05fr);
    margin-top: 14px !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    padding-top: 0 !important;
    padding-left: 24px !important;
    padding-right: 24px !important;
    box-sizing: border-box !important;
    width: 100% !important;
    max-width: 100% !important;
    overflow-x: hidden !important;
    gap: 0 !important;
}
[class*="st-key-orders_table_grid"] [data-testid="element-container"],
[class*="st-key-orders_table_grid"] [class*="st-key-orders_row_"] {
    margin-left: 0 !important;
    margin-right: 0 !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    max-width: 100% !important;
}
[class*="st-key-orders_table_grid"] [data-testid="element-container"]:has([class*="orders_row_"]) {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}
.il-orders-head-cell {
    color: var(--ink-3);
    font-size: var(--type-table-head);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .3px;
    padding: 0 2px;
    margin: 0;
    box-sizing: border-box;
    white-space: nowrap;
    overflow: visible;
    text-overflow: clip;
    min-width: 0;
    word-break: normal;
    overflow-wrap: normal;
    line-height: 1.2;
    hyphens: none;
    vertical-align: middle;
}
.il-orders-status-cell {
    display: inline-flex;
    align-items: center;
    padding: 0;
    background: transparent;
    box-shadow: none;
    border: none;
    box-sizing: border-box;
    white-space: nowrap;
    width: fit-content;
    max-width: 100%;
    overflow: visible;
    vertical-align: middle;
    align-self: center;
}
.il-orders-status-cell .il-pill {
    display: inline-flex !important;
    align-items: center !important;
    width: fit-content !important;
    max-width: none !important;
    white-space: nowrap !important;
    overflow: visible !important;
}
.il-orders-status-cell.is-selected {
    box-shadow: none !important;
    background: transparent !important;
    border: none !important;
}
[class*="st-key-orders_table_grid"] [data-testid="stHorizontalBlock"],
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] [data-testid="stHorizontalBlock"] {
    display: grid !important;
    grid-template-columns: var(--orders-grid-cols) !important;
    column-gap: 20px !important;
    row-gap: 0 !important;
    align-items: center !important;
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    box-sizing: border-box !important;
}
@container orders-card (max-width: 1200px) {
    [class*="st-key-orders_table_grid"] {
        --orders-grid-cols: minmax(0, 1.45fr) minmax(0, 1.45fr) minmax(0, 1.25fr) minmax(0, 0.55fr) minmax(0, 0.65fr) minmax(0, 1.45fr) minmax(0, 1.35fr) minmax(0, 1.15fr) minmax(0, 1.05fr);
    }
}
@container orders-card (max-width: 900px) {
    [class*="st-key-orders_table_grid"] {
        --orders-grid-cols: minmax(0, 1.45fr) minmax(0, 1.45fr) minmax(0, 1.25fr) minmax(0, 0.55fr) minmax(0, 0.65fr) minmax(0, 1.45fr) minmax(0, 1.35fr) minmax(0, 1.15fr) minmax(0, 1.05fr);
    }
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] {
    min-height: 0 !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    box-sizing: border-box !important;
    max-width: 100% !important;
}
[class*="st-key-orders_table_grid"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has([class*="orders_row_"]),
[class*="st-key-orders_table_grid"] > [data-testid="stVerticalBlock"] > [data-testid="element-container"]:has([class*="orders_row_"]) {
    margin: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
    height: auto !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] > [data-testid="stElementContainer"],
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] > [data-testid="element-container"] {
    margin: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
    height: auto !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] [data-testid="stColumn"] > [data-testid="stElementContainer"],
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] [data-testid="stColumn"] > [data-testid="element-container"] {
    margin: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
    height: auto !important;
}
[class*="st-key-orders_table_grid"] [data-testid="stHorizontalBlock"]:has(.il-orders-head-cell),
[class*="st-key-orders_table_grid"] > [data-testid="stLayoutWrapper"]:first-child > [data-testid="stHorizontalBlock"] {
    height: auto !important;
    min-height: 46px !important;
    padding-top: 8px !important;
    padding-bottom: 14px !important;
    box-sizing: border-box !important;
    overflow: visible !important;
    align-items: center !important;
    border-bottom: 1px solid #E1E5EA !important;
    border-top: none !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] [data-testid="stHorizontalBlock"] {
    min-height: 72px !important;
    height: auto !important;
    max-height: none !important;
    padding-top: 8px !important;
    padding-bottom: 8px !important;
    box-sizing: border-box !important;
    align-items: center !important;
    row-gap: 0 !important;
    margin: 0 !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"][data-testid="stVerticalBlock"],
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    height: auto !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] div[data-testid="stButton"] {
    margin: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
    height: auto !important;
}
[class*="st-key-orders_table_grid"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
[class*="st-key-il_orders_card"] [class*="st-key-orders_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    box-sizing: border-box !important;
    min-width: 0 !important;
    width: auto !important;
    max-width: 100% !important;
    flex: unset !important;
    align-self: center !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    overflow: visible !important;
}
[class*="st-key-orders_table_grid"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4) .il-orders-head-cell,
[class*="st-key-orders_table_grid"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(5) .il-orders-head-cell {
    text-align: right;
}
[class*="st-key-il_orders_card"] [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    border-bottom: none !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"] div[data-testid="stButton"] button {
    min-height: 0 !important;
    height: auto !important;
    max-height: none !important;
    white-space: normal !important;
    text-align: left !important;
    justify-content: flex-start !important;
    align-items: center !important;
    align-self: center !important;
    background: transparent !important;
    color: var(--ink) !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    padding: 0 4px !important;
    cursor: pointer !important;
    font-size: var(--type-table) !important;
    font-weight: 500 !important;
    line-height: 1.25 !important;
    box-sizing: border-box !important;
    vertical-align: middle;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_po"] div[data-testid="stButton"] button {
    white-space: nowrap !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_vendor"] div[data-testid="stButton"] button {
    white-space: normal !important;
    word-break: normal !important;
    overflow-wrap: normal !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_store"] div[data-testid="stButton"] button {
    white-space: nowrap !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_items"] div[data-testid="stButton"] button {
    white-space: nowrap !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_value"] div[data-testid="stButton"] button {
    white-space: nowrap !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_expected"] div[data-testid="stButton"] button {
    white-space: nowrap !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_approved"] div[data-testid="stButton"] button {
    white-space: normal !important;
    word-break: normal !important;
    overflow-wrap: normal !important;
    line-height: 1.25 !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_action"] div[data-testid="stButton"] button {
    white-space: normal !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
    line-height: 1.25 !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_items"] div[data-testid="stButton"] button,
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"][class*="_value"] div[data-testid="stButton"] button {
    justify-content: flex-end !important;
    text-align: right !important;
}
[class*="st-key-il_orders_card"] [class*="st-key-orders_sel_"] div[data-testid="stButton"] button:hover {
    background: var(--hover) !important;
}
.il-po-detail-id {
    font-size: 15px;
    font-weight: 600;
    color: var(--ink);
    line-height: 1.3;
    margin: 22px 0 16px 0;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    min-width: 0;
    text-align: left;
}
/* Fills the centered Streamlit title/body column */
.modal-inner,
.modal-content,
.il-po-modal-content {
    width: 100% !important;
    max-width: 960px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    box-sizing: border-box !important;
    min-width: 0;
    text-align: left;
}
.metadata-grid,
.il-po-detail-meta {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    column-gap: 48px;
    row-gap: 18px;
    margin: 0 0 28px 0;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    min-width: 0;
}
.metadata-grid > *,
.il-po-detail-meta > * {
    min-width: 0;
    text-align: left;
}
.status-cell {
    min-width: 0;
    overflow: visible;
}
.il-po-detail-meta .lab {
    display: block;
    font-size: 12px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.3px;
    margin: 0 0 4px 0;
}
.il-po-detail-meta .val {
    color: var(--ink);
    font-size: 15px;
    line-height: 1.35;
    margin: 0;
    min-width: 0;
}
.il-po-detail-meta .val .il-pill,
.status-cell .il-pill {
    white-space: nowrap;
    display: inline-block;
    max-width: 100%;
}
.il-po-detail-lines-title {
    font-size: var(--type-section, 16px);
    font-weight: var(--weight-section, 650);
    color: var(--ink);
    margin: 0 0 10px 0;
    line-height: 1.3;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    text-align: left;
}
.il-po-lines-table {
    margin: 0 0 4px 0;
    padding-bottom: 18px;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    min-width: 0;
}
.il-po-lines-table .il-queue-head,
.il-po-lines-table .il-queue-row,
.line-items-grid {
    display: grid !important;
    grid-template-columns:
        1fr
        2fr
        0.65fr
        0.85fr
        0.9fr !important;
    column-gap: 18px !important;
    row-gap: 0 !important;
    gap: 0 18px !important;
    align-items: center;
    padding-top: 12px !important;
    padding-bottom: 12px !important;
    min-height: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}
.metadata-grid > *,
.line-items-grid > *,
.il-po-lines-table .il-queue-head > *,
.il-po-lines-table .il-queue-row > * {
    min-width: 0;
}
.il-po-lines-table .il-queue-head {
    padding-top: 10px !important;
    padding-bottom: 10px !important;
}
.il-po-lines-table .il-queue-head > div:nth-child(1),
.il-po-lines-table .il-queue-row > div:nth-child(1),
.il-po-lines-table .il-queue-head > div:nth-child(2),
.il-po-lines-table .il-queue-row > div:nth-child(2) {
    text-align: left;
}
.il-po-lines-table .num,
.il-po-lines-table .il-queue-head > div:nth-child(3),
.il-po-lines-table .il-queue-head > div:nth-child(4),
.il-po-lines-table .il-queue-head > div:nth-child(5) {
    text-align: right;
}
/*
 * Purchase Order Details — real Streamlit dialog DOM:
 *   div[data-testid="stDialog"]                 (overlay — main-content only)
 *     > div                                     (WHITE CARD)
 *       > section[role="dialog"]
 *         > button[aria-label="Close"]
 *         > h2
 *         > div
 */
/* Overlay covers main content only — right of the fixed rail */
div[data-testid="stDialog"],
div[data-testid="stModal"] {
    position: fixed !important;
    top: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    left: var(--rail-w) !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    z-index: 100000 !important;
    pointer-events: auto !important;
    box-sizing: border-box !important;
}
/* WHITE DIALOG CARD — fit inside main-content overlay */
div[data-testid="stDialog"] > div:has(> [role="dialog"]),
div[data-testid="stModal"] > div:has(> [role="dialog"]) {
    position: relative !important;
    width: min(1050px, calc(100% - 64px)) !important;
    max-width: 1050px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    transform: none !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
}
/* Dialog section fills the white card */
div[data-testid="stDialog"] > div:has(> [role="dialog"]) > [role="dialog"],
div[data-testid="stModal"] > div:has(> [role="dialog"]) > [role="dialog"],
section[role="dialog"] {
    position: static !important;
    top: auto !important;
    left: auto !important;
    right: auto !important;
    bottom: auto !important;
    width: 100% !important;
    max-width: 100% !important;
    margin: 0 !important;
    transform: none !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: stretch !important;
    justify-content: flex-start !important;
}
/* Title + body share ONE centered content column */
div[data-testid="stDialog"] [role="dialog"] > h2,
div[data-testid="stModal"] [role="dialog"] > h2,
section[role="dialog"] > h2,
div[data-testid="stDialog"] [role="dialog"] > div,
div[data-testid="stModal"] [role="dialog"] > div,
section[role="dialog"] > div {
    width: 100% !important;
    max-width: 960px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    box-sizing: border-box !important;
    text-align: left !important;
}
/* Title clears the absolute X; no independent left offset vs body */
div[data-testid="stDialog"] [role="dialog"] > h2,
div[data-testid="stModal"] [role="dialog"] > h2,
section[role="dialog"] > h2 {
    padding-left: 0 !important;
    padding-right: 48px !important;
    padding-top: 24px !important;
    padding-bottom: 12px !important;
    justify-content: flex-start !important;
}
div[data-testid="stDialog"] [role="dialog"] > div,
div[data-testid="stModal"] [role="dialog"] > div,
section[role="dialog"] > div {
    padding-left: 0 !important;
    padding-right: 0 !important;
}
div[data-testid="stDialog"] [role="dialog"] [data-testid="stVerticalBlock"],
div[data-testid="stDialog"] [role="dialog"] [data-testid="stElementContainer"],
div[data-testid="stDialog"] [role="dialog"] [data-testid="stMarkdownContainer"],
section[role="dialog"] [data-testid="stVerticalBlock"],
section[role="dialog"] [data-testid="stElementContainer"],
section[role="dialog"] [data-testid="stMarkdownContainer"] {
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    min-width: 0 !important;
}
div[data-testid="stDialog"] [data-testid="stMarkdownContainer"] > p,
div[data-testid="stModal"] [data-testid="stMarkdownContainer"] > p,
section[role="dialog"] [data-testid="stMarkdownContainer"] > p {
    margin-bottom: 0 !important;
}
/* Close X — DO NOT CHANGE (top-right of white card) */
div[data-testid="stDialog"] > div:has(> [role="dialog"]) button[aria-label="Close"],
div[data-testid="stModal"] > div:has(> [role="dialog"]) button[aria-label="Close"],
div[data-testid="stDialog"] [role="dialog"] > button[aria-label="Close"],
div[data-testid="stModal"] [role="dialog"] > button[aria-label="Close"],
section[role="dialog"] > button[aria-label="Close"] {
    position: absolute !important;
    top: 20px !important;
    right: 24px !important;
    left: auto !important;
    bottom: auto !important;
    z-index: 10 !important;
    margin: 0 !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    width: 32px !important;
    min-width: 32px !important;
    max-width: 32px !important;
    height: 32px !important;
    min-height: 32px !important;
    max-height: 32px !important;
    flex: none !important;
    transform: none !important;
    align-self: auto !important;
}
@media (max-width: 1100px) {
    .il-status-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .il-kpi-row-compact { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
}

.il-filter-row {
    margin: 4px 0 14px 0;
}
.il-inline-summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 12px;
    padding: 4px 12px;
    margin: 0 0 12px 0;
    min-height: 32px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 8px;
    font-size: var(--type-body);
    color: var(--ink);
    line-height: 1.3;
    box-sizing: border-box;
}
.il-inline-summary .sep { color: var(--ink-3); }
.il-inline-summary b {
    font-variant-numeric: tabular-nums;
    font-weight: 700;
}
/* Today's Decisions page */
.il-queue-no-action {
    background: #f3faf5;
    border: 1px solid #b7e4c7;
    border-radius: 12px;
    padding: 22px 24px;
    margin: 0 0 18px 0;
    box-sizing: border-box;
}
.il-queue-no-action-kicker {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #15803d;
    margin-bottom: 8px;
}
.il-queue-no-action-title {
    font-size: 24px;
    font-weight: 700;
    color: var(--navy);
    line-height: 1.2;
    margin-bottom: 8px;
}
.il-queue-no-action-body {
    margin: 0;
    font-size: 15px;
    line-height: 1.45;
    color: var(--ink-2);
}
.il-queue-activity-heading {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ink-2);
    margin: 0 0 18px 0;
}
.agent-activity-list {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin: 0 0 22px 0;
    padding: 0;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
    box-sizing: border-box;
}
.agent-activity-row {
    display: grid;
    grid-template-columns: 64px minmax(0, 1fr) auto;
    align-items: center;
    min-height: 76px;
    padding: 0 28px;
    margin: 0;
    box-sizing: border-box;
    border-bottom: 1px solid #E2E8F0;
}
.agent-activity-row:last-child {
    border-bottom: none;
}
.activity-count {
    font-size: 22px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}
.activity-count.is-auto {
    color: #15803d;
}
.activity-count.is-blocked {
    color: #c2410c;
}
.activity-count.is-no-order {
    color: #1d4ed8;
}
.activity-label {
    font-size: 15px;
    font-weight: 500;
    color: var(--navy);
}
.activity-action {
    justify-self: end;
}
.activity-action-link {
    color: var(--navy);
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    white-space: nowrap;
}
.activity-action-link:hover {
    color: var(--ink);
    text-decoration: underline;
}
div[class*="st-key-queue_prior_analyses"] {
    margin: 0 0 12px 0 !important;
}
div[class*="st-key-queue_prior_analyses"] [data-testid="stExpander"] {
    margin: 0 !important;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
}
div[class*="st-key-queue_prior_analyses"] details summary {
    min-height: 44px !important;
    padding: 10px 16px !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    color: var(--navy) !important;
}
div[class*="st-key-queue_filter_row"] {
    margin: 0 0 12px 0 !important;
}
div[class*="st-key-queue_filter_row"] [data-testid="stHorizontalBlock"] {
    gap: 14px !important;
    flex-wrap: nowrap !important;
}
div[class*="st-key-queue_filter_row"] [data-baseweb="select"] > div {
    min-height: 36px !important;
    height: 36px !important;
}
div[class*="st-key-queue_filter_row"] [data-testid="stButton"] button {
    min-height: 36px !important;
    height: 36px !important;
}
/* —— Dense operational tables —— */
.il-queue-table {
    width: 100%;
    font-size: var(--type-table);
    color: var(--ink);
}
.il-queue-head,
.il-queue-row {
    display: grid;
    grid-template-columns: 1.6fr 0.8fr 0.7fr 1.1fr 0.7fr 0.7fr 0.7fr 0.7fr 0.8fr 0.9fr 0.2fr;
    gap: 8px;
    align-items: center;
    min-height: var(--row-h);
    padding: 6px 4px;
    border-bottom: 1px solid var(--line);
}
.il-decisions-table .il-queue-head,
.il-decisions-table .il-queue-row {
    display: grid !important;
    grid-template-columns:
        0.72fr
        1.15fr
        1.50fr
        1.45fr
        1.70fr
        0.85fr
        0.85fr
        1.05fr !important;
    column-gap: 14px !important;
    gap: 0 14px !important;
    align-items: center;
    padding-top: 12px !important;
    padding-bottom: 12px !important;
    min-height: 0 !important;
    font-size: var(--type-table);
}
.il-decisions-table .il-queue-head {
    padding-top: 8px !important;
    padding-bottom: 8px !important;
}
.il-decisions-why {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.35;
    min-width: 0;
}
.il-decisions-table .il-queue-head > div:nth-child(7),
.il-decisions-table .num {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.il-decisions-badge {
    display: flex;
    align-items: center;
    min-width: 0;
}
.il-decisions-table .il-pill {
    white-space: nowrap;
}
.il-decisions-table .il-queue-row.is-selected {
    background: #EAF2FA !important;
}
div[class*="st-key-queue_decisions_wrap"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
div[class*="st-key-queue_row_hit_"] {
    position: relative !important;
}
div[class*="st-key-queue_row_hit_"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
div[class*="st-key-queue_row_nav_"] {
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    top: 0 !important;
    bottom: 0 !important;
    height: auto !important;
    max-height: none !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 1 !important;
}
div[class*="st-key-queue_row_nav_"] div[data-testid="stButton"] {
    margin: 0 !important;
    height: 100% !important;
}
div[class*="st-key-queue_row_nav_"] div[data-testid="stButton"] > button,
div[class*="st-key-queue_row_nav_"] div[data-testid="stButton"] > button:hover,
div[class*="st-key-queue_row_nav_"] div[data-testid="stButton"] > button:focus,
div[class*="st-key-queue_row_nav_"] div[data-testid="stButton"] > button:active {
    height: 100% !important;
    min-height: 100% !important;
    width: 100% !important;
    opacity: 0 !important;
    cursor: pointer !important;
    border: none !important;
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: none !important;
    color: transparent !important;
    pointer-events: auto !important;
}
div[class*="st-key-queue_row_hit_"] [data-testid="stElementContainer"]:has(.il-queue-row) {
    margin: 0 !important;
    padding: 0 !important;
    position: relative !important;
    z-index: 2 !important;
    pointer-events: none !important;
}
div[class*="st-key-queue_row_hit_"] .il-decisions-table,
div[class*="st-key-queue_row_hit_"] .il-queue-row {
    pointer-events: none !important;
}
div[class*="st-key-queue_row_hit_"]:hover .il-queue-row,
div[class*="st-key-queue_row_hit_"]:has(div[class*="st-key-queue_row_nav_"]:hover) .il-queue-row {
    background: #F7F9FC !important;
}
div[class*="st-key-queue_row_hit_"] .il-queue-row.is-selected,
div[class*="st-key-queue_row_hit_"]:hover .il-queue-row.is-selected {
    background: #EAF2FA !important;
}
.il-queue-head {
    color: var(--ink-3);
    font-size: var(--type-table-head);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .3px;
    border-bottom: 1px solid var(--line);
    min-height: 28px;
}
.il-queue-row:hover {
    background: var(--hover);
}
.il-queue-row:focus-within {
    outline: 2px solid color-mix(in srgb, var(--navy) 35%, transparent);
    outline-offset: -2px;
}
.il-queue-table .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.il-queue-table .il-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-1);
}
@media (max-width: 1100px) {
    .il-decisions-table { font-size: var(--type-caption); }
}
.il-policy-table .il-queue-head,
.il-policy-table .il-queue-row {
    grid-template-columns: 1.1fr 2.2fr 1fr 1fr;
    align-items: start;
}
.il-policy-table .il-policy-explain {
    color: var(--ink-2);
    line-height: 1.35;
    font-size: var(--type-caption);
}
.il-policy-table code {
    font-size: var(--type-caption);
    color: var(--ink-3);
}
.il-health-table .il-queue-head,
.il-health-table .il-queue-row {
    grid-template-columns: 1.4fr 0.6fr 0.7fr 2.2fr;
    align-items: start;
}
.il-health-deps .il-queue-head,
.il-health-deps .il-queue-row {
    grid-template-columns: 1.2fr 1.4fr 0.7fr 0.6fr 2fr;
    align-items: start;
}
.il-health-sub {
    font-size: var(--type-caption);
    color: var(--ink-3);
    margin-top: 2px;
    font-weight: 500;
}
.il-fact-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 4px 0 12px 0;
}
.il-fact-chip {
    display: inline-block;
    background: rgba(15, 40, 71, 0.06);
    border: 1px solid var(--line);
    color: var(--ink);
    font-size: 12px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    padding: 5px 10px;
    border-radius: 8px;
    line-height: 1.3;
}

.il-panel {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    box-shadow: none;
    padding: var(--space-3) var(--space-4);
    margin-bottom: var(--space-3);
}
.il-panel-title, .il-panel h3 {
    font-size: var(--type-card);
    font-weight: var(--weight-card);
    color: var(--ink-2);
    text-transform: uppercase;
    letter-spacing: .04em;
    margin: 0 0 var(--space-2) 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
}
.il-panel-title .hint, .il-panel h3 .hint {
    font-size: var(--type-caption);
    color: var(--ink-3);
    font-weight: 500;
    text-transform: none;
    letter-spacing: 0;
}
.il-dd-human-decision-title,
.stApp h3.il-dd-human-decision-title,
[data-testid="stMarkdownContainer"] h3.il-dd-human-decision-title {
    font-size: 18px !important;
    font-weight: 700 !important;
    line-height: 1.3 !important;
    justify-content: flex-start !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--card) !important;
    border: 1px solid var(--line) !important;
    border-radius: 10px !important;
    box-shadow: none;
    padding: 6px 8px 4px 8px;
    margin-bottom: var(--space-3);
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
    font-size: var(--type-caption);
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: .4px;
    font-weight: 600;
    margin-bottom: 4px;
}
.il-meta-line {
    font-size: var(--type-caption);
    color: var(--ink-2);
    margin-top: var(--space-2);
}
.il-meta-line strong { color: var(--ink); }

/* Status system — text + tone; color is not the only cue */
.il-pill {
    font-size: var(--type-caption);
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 6px;
    letter-spacing: .1px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    line-height: 1.35;
    border: 1px solid transparent;
    max-width: 100%;
    white-space: nowrap;
}
.il-pill.success, .il-pill.ok {
    background: var(--status-success-bg);
    color: var(--status-success);
    border-color: color-mix(in srgb, var(--status-success) 25%, transparent);
}
.il-pill.attention, .il-pill.warn {
    background: var(--status-attention-bg);
    color: var(--status-attention);
    border-color: color-mix(in srgb, var(--status-attention) 25%, transparent);
}
.il-pill.warning {
    background: var(--status-warning-bg);
    color: var(--status-warning);
    border-color: color-mix(in srgb, var(--status-warning) 30%, transparent);
}
.il-pill.critical, .il-pill.danger {
    background: var(--status-critical-bg);
    color: var(--status-critical);
    border-color: color-mix(in srgb, var(--status-critical) 25%, transparent);
}
.il-pill.progress, .il-pill.info {
    background: var(--status-progress-bg);
    color: var(--status-progress);
    border-color: color-mix(in srgb, var(--status-progress) 25%, transparent);
}
.il-pill.neutral {
    background: var(--status-neutral-bg);
    color: var(--status-neutral);
    border-color: var(--line);
}

/* —— Business empty state —— */
.il-empty {
    padding: var(--space-2) var(--space-1);
    margin: 0;
    max-width: 40rem;
}
.il-empty-title {
    font-size: var(--type-section);
    font-weight: var(--weight-section);
    color: var(--ink);
    margin: 0 0 var(--space-2) 0;
    line-height: 1.25;
}
.il-empty-body {
    font-size: var(--type-body);
    color: var(--ink-2);
    margin: 0 0 var(--space-2) 0;
    line-height: 1.45;
}
.il-empty-next {
    font-size: var(--type-body);
    color: var(--ink);
    margin: 0 0 var(--space-3) 0;
    line-height: 1.45;
}
.il-empty-meta {
    font-size: var(--type-caption);
    color: var(--ink-3);
    margin: 0 0 var(--space-3) 0;
}
.il-empty-actions { margin-top: var(--space-2); }

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
    font-size: var(--type-caption);
    font-weight: 600;
    letter-spacing: .4px;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.il-welcome .val {
    color: var(--ink);
    font-size: var(--type-body);
    font-weight: 600;
    margin-bottom: 12px;
}
.il-welcome .val:last-child { margin-bottom: 0; }

.secondary-text {
    color: var(--ink-2);
    font-size: var(--type-caption);
    text-align: left;
}
.agent-explanation {
    color: var(--ink);
    line-height: 1.55;
    font-size: var(--type-body);
    text-align: left;
    margin: 10px 0 0 0;
}

/* Recommendation Detail — decision record / evidence */
.block-container:has(.il-detail-page),
section.stMain .block-container:has(.il-detail-page) {
    padding-top: 10px !important;
}
.il-detail-page {
    max-width: 1180px;
    width: 92%;
    margin: 0 auto;
    padding: 4px 28px 24px;
    box-sizing: border-box;
}
.il-dd-page-head {
    margin: 0 0 14px 0;
}
.il-dd-page-head h1 {
    margin: 0;
    font-size: 30px;
    font-weight: 700;
    color: var(--navy);
    letter-spacing: -0.02em;
    line-height: 1.2;
}
.il-dd-page-head p {
    margin: 8px 0 0 0;
    font-size: 15px;
    color: var(--ink-2);
    line-height: 1.4;
}
div[class*="st-key-dd_back_link"] {
    margin: 0 0 0 0 !important;
    padding: 0 !important;
}
div[class*="st-key-dd_back_link"] [data-testid="stElementContainer"] {
    margin: 0 !important;
    padding: 0 !important;
}
div[class*="st-key-dd_back_link"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
div[class*="st-key-dd_back_link"] div[data-testid="stButton"] {
    margin: 0 !important;
}
div[class*="st-key-dd_back_link"] div[data-testid="stButton"] > button {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: var(--status-progress) !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    min-height: 24px !important;
    height: auto !important;
    padding: 0 !important;
    justify-content: flex-start !important;
}
div[class*="st-key-dd_back_link"] div[data-testid="stButton"] > button:hover {
    background: transparent !important;
    color: #1d4ed8 !important;
    text-decoration: underline;
}

.il-dd-summary {
    display: grid;
    grid-template-columns: 1.38fr 0.82fr;
    column-gap: 24px;
    background: #fff;
    border: 1px solid #DCE3EA;
    border-radius: 12px;
    padding: 18px 26px;
    box-sizing: border-box;
    min-width: 0;
    height: auto;
}
.il-dd-summary.is-review {
    grid-template-columns: 1fr 1.2fr 1fr;
    align-items: center;
    column-gap: 0;
    border-radius: 16px;
    padding: 20px 28px;
    min-height: 0 !important;
    height: auto !important;
}
.il-dd-summary.is-review .il-dd-sum-col {
    min-width: 0;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 8px 20px;
}
.il-dd-summary.is-review .il-dd-sum-col.left {
    align-items: flex-start;
    text-align: left;
    padding-left: 6px;
}
.il-dd-summary.is-review .il-dd-sum-col.center,
.il-dd-summary.is-review .il-dd-sum-col.right {
    align-items: center;
    text-align: center;
    border-left: 1px solid #DCE3EA;
}
.il-dd-summary.is-review .il-dd-sum-col.right {
    padding-right: 6px;
}
.il-dd-summary.is-review .il-dd-attn-eyebrow {
    font-size: 10px !important;
    font-weight: 700 !important;
    color: var(--status-critical) !important;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    line-height: 1.3 !important;
}
.il-dd-summary.is-review .il-dd-attn-title {
    font-size: 21px !important;
    font-weight: 700 !important;
    color: var(--status-critical) !important;
    margin-top: 8px !important;
    line-height: 1.2 !important;
}
.il-dd-summary.is-review .il-dd-attn-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px !important;
}
.il-dd-summary.is-review .il-dd-attn-pills .il-pill {
    font-size: 11px !important;
    padding: 3px 7px !important;
}
.il-dd-summary.is-review .il-dd-attn-rule {
    border-top: 1px solid #DCE3EA;
    margin: 14px 0 !important;
    width: 100%;
}
.il-dd-summary.is-review .il-dd-attn-shortage {
    font-size: 18px !important;
    font-weight: 700 !important;
    color: var(--status-critical) !important;
    line-height: 1.2 !important;
}
.il-dd-summary.is-review .il-dd-attn-gap {
    margin-top: 2px !important;
    font-size: 12px !important;
    font-weight: 400 !important;
    color: var(--ink-3) !important;
}
.il-dd-summary.is-auto .il-dd-attn-eyebrow {
    color: #167A38 !important;
}
.il-dd-summary.is-auto .il-dd-attn-title {
    color: #167A38 !important;
}
.il-dd-summary.is-auto .il-dd-attn-gap {
    margin-top: 0 !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: var(--ink-2) !important;
}
.il-dd-summary.is-auto .il-dd-attn-pills .il-dd-pill {
    font-size: 11px !important;
    padding: 3px 7px !important;
}
.il-dd-summary.is-review .il-dd-sum-product {
    font-size: 24px !important;
    font-weight: 700 !important;
    color: var(--navy) !important;
    text-align: center;
    line-height: 1.15 !important;
    margin: 0 !important;
}
.il-dd-summary.is-review .il-dd-sum-sku {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-top: 8px !important;
    padding: 4px 10px !important;
    border: 1px solid #DCE3EA;
    border-radius: 8px;
    background: #F5F7FA;
    font-size: 12px !important;
    font-weight: 600 !important;
    color: var(--ink-2) !important;
    line-height: 1.3 !important;
}
.il-dd-summary.is-review .il-dd-sum-store {
    margin-top: 12px !important;
    font-size: 14px !important;
    font-weight: 400 !important;
    color: var(--ink-2) !important;
    line-height: 1.35 !important;
}
.il-dd-summary.is-review .il-dd-sum-vendor {
    margin-top: 8px !important;
    font-size: 14px !important;
    font-weight: 400 !important;
    color: var(--ink-2) !important;
    line-height: 1.35 !important;
}
.il-dd-summary.is-review .il-dd-action-label {
    font-size: 10px !important;
    font-weight: 700 !important;
    color: #167A38 !important;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    margin-bottom: 0 !important;
}
.il-dd-summary.is-review .il-dd-action-primary {
    font-size: 23px !important;
    font-weight: 700 !important;
    color: #167A38 !important;
    margin-top: 8px !important;
    line-height: 1.15 !important;
}
.il-dd-summary.is-review .il-dd-action-secondary {
    margin-top: 6px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    color: var(--ink-2) !important;
}
.il-dd-summary.is-review .il-dd-value-card.is-review {
    margin-top: 16px !important;
    padding: 12px 18px !important;
    border: 1px solid #BFDFD2;
    border-radius: 10px;
    background: #FFFFFF;
    display: inline-block;
    min-width: 200px;
    box-sizing: border-box;
}
.il-dd-summary.is-review .il-dd-value-card.is-review .lab {
    font-size: 12px !important;
    font-weight: 600 !important;
    color: var(--ink-3) !important;
    margin-bottom: 0 !important;
}
.il-dd-summary.is-review .il-dd-value-card.is-review .val {
    margin-top: 5px !important;
    font-size: 22px !important;
    font-weight: 700 !important;
    color: var(--navy) !important;
}
.il-dd-summary-left,
.il-dd-summary-right {
    min-width: 0;
    box-sizing: border-box;
}
.il-dd-summary-left {
    border-right: 1px solid #DCE3EA;
    padding-right: 20px;
}
.il-dd-summary-right {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    text-align: center;
    padding-left: 4px;
    gap: 0;
}
.il-dd-product {
    font-size: 26px;
    font-weight: 700;
    color: var(--navy);
    line-height: 1.2;
    margin: 0 0 10px 0;
}
.il-dd-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    row-gap: 10px;
    column-gap: 10px;
    font-size: 14px;
    color: var(--ink-2);
    margin-bottom: 10px;
}
.il-dd-meta b { color: var(--ink); font-weight: 600; }
.il-dd-meta .dot { color: var(--ink-3); }
.il-dd-status-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    row-gap: 10px;
    column-gap: 12px;
    font-size: 14px;
    color: var(--ink-2);
}
.il-dd-status-row b { color: var(--ink); }
.il-dd-pill {
    display: inline-flex;
    align-items: center;
    background: #EAF7EE;
    color: #167A38;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 12px;
    line-height: 1.3;
    white-space: nowrap;
}
.il-dd-info {
    color: var(--ink-3);
    font-size: 13px;
    margin-left: 2px;
}
.il-dd-summary p.il-dd-sentence,
.il-dd-sentence {
    margin: 30px 0 0 0 !important;
    font-size: 15px !important;
    line-height: 1.4 !important;
    color: var(--ink);
    max-width: 100% !important;
}
.il-dd-action-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.4px;
    margin-bottom: 4px;
}
.il-dd-action-primary {
    font-size: 26px;
    font-weight: 700;
    color: #167A38;
    line-height: 1.15;
    letter-spacing: -0.02em;
}
.il-dd-action-secondary {
    margin-top: 6px;
    font-size: 15px;
    font-weight: 500;
    color: var(--ink-2);
}
.il-dd-value-card {
    margin-top: 14px;
    padding: 12px 18px;
    border: 1px solid #DCE3EA;
    border-radius: 8px;
    text-align: center;
    background: #fff;
    min-width: 148px;
    min-height: auto;
    box-sizing: border-box;
}
.il-dd-value-card .lab {
    font-size: 12px;
    color: var(--ink-3);
    font-weight: 600;
    margin-bottom: 2px;
}
.il-dd-value-card .val {
    font-size: 20px;
    font-weight: 700;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
}

div[class*="st-key-dd_policy_card"] {
    margin-top: 14px !important;
    margin-bottom: 0 !important;
    background: #fff !important;
    border: 1px solid #DCE3EA !important;
    border-radius: 12px !important;
    padding: 14px 18px 16px !important;
    box-sizing: border-box !important;
}
div[class*="st-key-dd_policy_card"] [data-testid="stHorizontalBlock"] {
    align-items: start !important;
    gap: 14px !important;
}
div[class*="st-key-dd_policy_card"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
div[class*="st-key-dd_policy_card"] [data-testid="column"] {
    padding: 0 !important;
}
.il-dd-policy-inner {
    display: grid;
    grid-template-columns: auto 1fr;
    column-gap: 14px;
    align-items: start;
    min-width: 0;
}
.il-dd-shield {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    flex: 0 0 auto;
    align-self: start;
    margin-top: 2px;
    background: transparent;
    border-radius: 0;
    color: var(--navy);
}
.il-dd-shield-svg {
    display: block;
    width: 26px;
    height: 26px;
}
.il-dd-policy-copy {
    min-width: 0;
}
.il-dd-policy-title-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 10px;
    margin-bottom: 0;
}
.il-dd-policy-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--navy);
}
.il-dd-policy-badge {
    font-size: 12px;
    font-weight: 600;
    border-radius: 6px;
    padding: 3px 8px;
}
.il-dd-policy-badge.ok { background: #EAF7EE; color: #167A38; }
.il-dd-policy-badge.warn { background: var(--status-attention-bg); color: var(--status-attention); }
.il-dd-policy-badge.danger { background: var(--status-critical-bg); color: var(--status-critical); }
.il-dd-policy-body {
    font-size: 13.5px;
    color: var(--ink-2);
    line-height: 1.4;
    margin-top: 3px;
    margin-bottom: 2px;
    padding-bottom: 0;
}
div[class*="st-key-dd_policy_card"] [data-testid="stPopover"] > button,
div[class*="st-key-dd_policy_card"] button[kind="secondary"] {
    background: #fff !important;
    border: 1px solid #DCE3EA !important;
    border-radius: 8px !important;
    padding: 7px 11px !important;
    min-height: 0 !important;
    height: auto !important;
    color: var(--ink) !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    white-space: nowrap !important;
    box-shadow: none !important;
}
div[class*="st-key-dd_policy_card"] [data-testid="stPopover"] > button:hover {
    background: var(--subtle) !important;
}
div[class*="st-key-dd_policy_card"] [data-testid="stPopoverBody"],
div[class*="st-key-dd_policy_card"] [data-testid="stPopover"] [data-testid="stVerticalBlock"] {
    min-width: 280px !important;
    max-width: 340px !important;
}
.il-dd-policy-popover {
    padding: 2px 2px 4px;
    box-sizing: border-box;
}
.il-dd-policy-popover-head {
    font-size: 14px;
    font-weight: 600;
    color: var(--navy);
    margin: 0 0 10px 0;
    line-height: 1.3;
}
.il-dd-policy-cond-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: 0 0 12px 0;
}
.il-dd-policy-cond-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
    font-size: 13.5px;
    line-height: 1.35;
}
.il-dd-policy-cond-row .lab {
    color: var(--ink-2);
    font-weight: 500;
}
.il-dd-policy-cond-row .val {
    color: var(--ink);
    font-weight: 600;
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.il-dd-policy-cond-footer {
    border-top: 1px solid #E5E9EF;
    padding-top: 10px;
}
.il-dd-policy-cond-footer .title {
    font-size: 14px;
    font-weight: 700;
    color: var(--navy);
    line-height: 1.3;
}
.il-dd-policy-cond-footer .sub {
    margin-top: 3px;
    font-size: 13px;
    font-weight: 400;
    color: var(--ink-2);
    line-height: 1.35;
}

.il-dd-section-title,
.stApp h3.il-dd-section-title,
[data-testid="stMarkdownContainer"] h3.il-dd-section-title {
    font-size: 20px !important;
    font-weight: 700 !important;
    line-height: 1.3 !important;
    color: #1f2937 !important;
    margin-top: 28px !important;
    margin-bottom: 14px !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    padding: 0 !important;
    background: none !important;
    border: none !important;
    text-decoration: none !important;
    letter-spacing: normal !important;
    text-transform: none !important;
}
.il-dd-evidence-strip {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 16px;
    width: 100%;
    align-items: stretch;
    margin-bottom: 0;
}
.il-dd-evidence-tile {
    background: #FFFFFF;
    border: 1px solid #DCE3EA;
    border-radius: 10px;
    padding: 16px 18px;
    min-height: 118px;
    min-width: 0;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
}
.il-dd-evidence-tile .lab {
    font-size: 12px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
.il-dd-evidence-tile .val {
    font-size: 26px;
    font-weight: 700;
    color: var(--navy);
    margin-top: 14px;
    font-variant-numeric: tabular-nums;
    line-height: 1.15;
}
.il-dd-evidence-tile .sub {
    font-size: 13px;
    color: var(--ink-3);
    margin-top: 4px;
}

.il-dd-rationale {
    margin-top: 0;
    padding: 0;
    border: 1px solid #DCE3EA;
    border-radius: 12px;
    background: #FFFFFF;
    box-sizing: border-box;
    overflow: hidden;
}
.il-dd-rat-row {
    display: grid;
    align-items: center;
    column-gap: 28px;
    padding: 20px 28px;
    border-top: 1px solid #E5E9EF;
    box-sizing: border-box;
    min-width: 0;
}
.il-dd-rat-row.is-first {
    border-top: none;
}
.il-dd-rat-row-demand {
    grid-template-columns: 240px 1.1fr 1fr;
}
.il-dd-rat-row-inventory {
    grid-template-columns: 240px 1.4fr 0.9fr;
}
.il-dd-rat-row-calc {
    grid-template-columns: 240px 1fr;
}
.il-dd-rat-row-policy {
    grid-template-columns: 240px 1fr auto;
}
.il-dd-rat-left {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    min-width: 0;
}
.il-dd-step-num {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    border: 2px solid var(--status-progress);
    color: var(--status-progress);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 600;
    background: #fff;
    flex: 0 0 auto;
    margin: 0;
}
.il-dd-rat-title {
    font-size: 17px;
    font-weight: 600;
    color: var(--navy);
    line-height: 1.25;
    margin: 0 0 6px 0;
}
.il-dd-rat-conclusion {
    font-size: 14.5px;
    font-weight: 400;
    color: var(--ink-2);
    line-height: 1.4;
    margin: 0;
}
.il-dd-rat-center,
.il-dd-rat-right {
    min-width: 0;
}
.il-dd-rat-sep {
    border-left: 1px solid #E5E9EF;
    padding-left: 24px;
    box-sizing: border-box;
}
.il-dd-rat-panel-lab {
    font-size: 11px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.35px;
    margin: 0 0 10px 0;
}
.il-dd-trend {
    width: 100%;
    height: 148px;
    display: block;
    overflow: visible;
}
.il-dd-trend-axis {
    fill: var(--ink-3);
    font-size: 10px;
    font-weight: 500;
    font-family: inherit;
}
.il-dd-trend-tip {
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
}
.il-dd-trend-point:hover .il-dd-trend-tip {
    opacity: 1;
    visibility: visible;
}
.il-dd-trend-tip-bg {
    fill: #1f2937;
    filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.12));
}
.il-dd-trend-tip-text {
    fill: #ffffff;
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    white-space: nowrap;
}
.il-dd-trend-empty {
    height: 148px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px dashed #DCE3EA;
    border-radius: 8px;
    color: var(--ink-3);
    font-size: 13px;
    padding: 12px;
    box-sizing: border-box;
    text-align: center;
}
.il-dd-support-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px 18px;
}
.il-dd-support-item .lab {
    font-size: 11px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
.il-dd-support-item .val {
    margin-top: 4px;
    font-size: 15px;
    font-weight: 600;
    color: var(--ink);
    line-height: 1.3;
}
.il-dd-inv-compare {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    column-gap: 14px;
    min-width: 0;
}
.il-dd-inv-side {
    min-width: 0;
}
.il-dd-inv-side .qty {
    font-size: 22px;
    font-weight: 700;
    line-height: 1.15;
    color: var(--ink);
}
.il-dd-inv-side.avail .qty {
    color: #167A38;
}
.il-dd-inv-side .lab {
    margin-top: 4px;
    font-size: 12px;
    font-weight: 600;
    color: var(--ink);
}
.il-dd-inv-side.avail .lab {
    color: #167A38;
}
.il-dd-inv-side .hint {
    margin-top: 2px;
    font-size: 11px;
    font-weight: 400;
    color: var(--ink-3);
    line-height: 1.3;
    white-space: nowrap;
}
.il-dd-inv-side.req {
    text-align: right;
}
.il-dd-inv-scale {
    min-width: 0;
    padding-top: 4px;
}
.il-dd-inv-track {
    position: relative;
    height: 14px;
    border-radius: 4px;
    background: #EEF1F5;
    overflow: visible;
}
.il-dd-inv-fill {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    background: #16A34A;
    border-radius: 4px 0 0 4px;
    max-width: 100%;
}
.il-dd-inv-marker {
    position: absolute;
    top: -5px;
    bottom: -5px;
    width: 0;
    border-left: 1.5px dashed #167A38;
    transform: translateX(-50%);
    pointer-events: none;
    z-index: 2;
}
.il-dd-inv-ticks {
    position: relative;
    height: 28px;
    margin-top: 4px;
}
.il-dd-inv-ticks .tick {
    position: absolute;
    top: 0;
    transform: translateX(-50%);
    text-align: center;
    line-height: 1;
}
.il-dd-inv-ticks .tick.start {
    transform: translateX(0);
    text-align: left;
}
.il-dd-inv-ticks .tick.end {
    transform: translateX(-100%);
    text-align: right;
}
.il-dd-inv-ticks .tick i {
    display: block;
    width: 1px;
    height: 7px;
    margin: 0 auto 4px auto;
    background: #C5CDD8;
}
.il-dd-inv-ticks .tick.start i {
    margin-left: 0;
}
.il-dd-inv-ticks .tick.end i {
    margin-left: auto;
    margin-right: 0;
}
.il-dd-inv-ticks .tick b {
    display: block;
    font-size: 11px;
    font-weight: 600;
    color: var(--ink-3);
    font-style: normal;
}
.il-dd-stockout-card {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    background: #FEF3C7;
    border: 1px solid #F6D58A;
    border-radius: 10px;
    padding: 12px 14px;
    box-sizing: border-box;
}
.il-dd-stockout-card .icon {
    color: #B45309;
    font-size: 16px;
    line-height: 1;
    margin-top: 1px;
}
.il-dd-stockout-card .title {
    font-size: 13px;
    font-weight: 700;
    color: #92400E;
}
.il-dd-stockout-card .sub {
    margin-top: 2px;
    font-size: 13px;
    color: #A16207;
}
.il-dd-calc-flow {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 6px;
}
.il-dd-calc-block {
    border: 1px solid #DCE3EA;
    border-radius: 10px;
    padding: 10px 12px;
    min-width: 92px;
    background: #fff;
    box-sizing: border-box;
    text-align: center;
}
.il-dd-calc-block .lab {
    font-size: 10px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
.il-dd-calc-block .val {
    margin-top: 4px;
    font-size: 18px;
    font-weight: 700;
    color: var(--navy);
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
}
.il-dd-calc-block .hint {
    margin-top: 2px;
    font-size: 11px;
    color: var(--ink-3);
}
.il-dd-calc-block.shortage {
    background: #FFFBEB;
    border-color: #F6D58A;
}
.il-dd-calc-block.recommended {
    background: #ECFDF3;
    border-color: #BBF7D0;
}
.il-dd-calc-block.cases {
    background: #EFF6FF;
    border-color: #BFDBFE;
}
.il-dd-calc-op {
    font-size: 18px;
    font-weight: 600;
    color: var(--ink-3);
    padding: 0 2px;
}
.il-dd-policy-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 18px 28px;
}
.il-dd-policy-metric .lab {
    font-size: 11px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
.il-dd-policy-metric .val {
    margin-top: 4px;
    font-size: 15px;
    font-weight: 600;
    color: var(--ink);
}
.il-dd-policy-metric .val.ok { color: #167A38; }
.il-dd-policy-metric .val.warn { color: #B45309; }
.il-dd-policy-metric .val.danger { color: #B91C1C; }
.il-dd-rat-expand {
    margin: 0 28px 16px 28px;
    padding: 14px 16px;
    border: 1px solid #E5E9EF;
    border-radius: 10px;
    background: #FAFBFC;
    box-sizing: border-box;
}
.il-dd-rat-expand .il-evidence-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px 24px;
}
.il-dd-rat-expand .il-evidence-row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font-size: 13px;
}
.il-dd-rat-expand .il-evidence-row .lab { color: var(--ink-3); font-weight: 600; }
.il-dd-rat-expand .il-evidence-row .val { color: var(--ink); font-weight: 600; }
div[class*="st-key-dd_rat_policy_action"] {
    margin: -56px 28px 18px auto !important;
    width: fit-content !important;
    position: relative !important;
    z-index: 2 !important;
}
div[class*="st-key-dd_rat_policy_action"] [data-testid="stPopover"] > button,
div[class*="st-key-dd_rat_policy_action"] button[kind="secondary"] {
    background: #fff !important;
    border: 1px solid #DCE3EA !important;
    border-radius: 8px !important;
    padding: 7px 11px !important;
    min-height: 0 !important;
    height: auto !important;
    color: var(--ink) !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    white-space: nowrap !important;
    box-shadow: none !important;
}
div[class*="st-key-dd_row_toggle"] div[data-testid="stButton"] > button {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    min-height: 28px !important;
    height: 28px !important;
    padding: 0 8px !important;
    color: var(--ink-3) !important;
    font-size: 18px !important;
}
@media (max-width: 1100px) {
    .il-dd-rat-row-demand,
    .il-dd-rat-row-inventory,
    .il-dd-rat-row-calc,
    .il-dd-rat-row-policy {
        grid-template-columns: 1fr;
        row-gap: 16px;
    }
    .il-dd-evidence-strip {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}

.il-dd-committed {
    display: grid;
    grid-template-columns: 1.6fr 0.7fr 0.8fr;
    align-items: center;
    border: 1px solid #DCE3EA;
    border-radius: 12px;
    padding: 18px 22px;
    margin-top: 14px;
    background: #fff;
    box-sizing: border-box;
    min-width: 0;
}
/* Outer gap between Decision committed and Ask a follow-up (keyed wrapper in 2_Review.py) */
div[class*="st-key-dd_follow_up"] {
    margin-top: 24px !important;
}
.il-dd-committed-left,
.il-dd-committed-mid,
.il-dd-committed-right {
    min-width: 0;
    box-sizing: border-box;
}
.il-dd-committed-left {
    display: flex;
    align-items: center;
    gap: 14px;
    padding-right: 18px;
}
.il-dd-committed-mid {
    border-left: 1px solid #E5E9EF;
    border-right: 1px solid #E5E9EF;
    padding: 0 18px;
}
.il-dd-committed-right {
    padding-left: 18px;
}
.il-dd-committed-check {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: #167A38;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    font-weight: 700;
    flex: 0 0 auto;
}
.il-dd-committed-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--navy);
}
.il-dd-committed-sub {
    font-size: 13px;
    color: var(--ink-2);
    margin-top: 2px;
}
.il-dd-committed .lab {
    font-size: 11px;
    font-weight: 600;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
.il-dd-committed .val {
    font-size: 14px;
    font-weight: 600;
    color: var(--ink);
    margin-top: 4px;
}

.il-decision-hero {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    box-shadow: none;
    padding: var(--space-3) var(--space-4);
    margin-bottom: var(--space-2);
}
.il-decision-hero-top {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: flex-start;
    flex-wrap: wrap;
}
.il-decision-hero-action {
    font-size: var(--type-section);
    font-weight: 700;
    letter-spacing: .02em;
    color: var(--brand);
    text-align: right;
    line-height: 1.15;
}
.il-decision-hero-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 16px;
    margin-top: var(--space-2);
    font-size: var(--type-caption);
    color: var(--ink-2);
}
.il-decision-hero-metrics b { color: var(--ink); }
.il-decision-hero-sentence {
    margin: 12px 0 0 0;
    font-size: var(--type-body);
    color: var(--ink);
    line-height: 1.45;
}
.il-evidence-strip {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: var(--space-3);
}
.il-evidence-chip {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 8px 10px;
    min-width: 0;
}
.il-evidence-chip .lab {
    display: block;
    font-size: var(--type-caption);
    font-weight: var(--weight-card);
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: .3px;
    margin-bottom: 2px;
}
.il-evidence-chip .val {
    font-size: var(--type-body);
    font-weight: 600;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
}
@media (max-width: 1100px) {
    .il-evidence-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .il-dd-evidence-strip { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .il-dd-summary { grid-template-columns: 1fr; }
    .il-dd-summary.is-review { grid-template-columns: 1fr; min-height: 0; padding: 24px 22px; }
    .il-dd-summary.is-review .il-dd-sum-col.center,
    .il-dd-summary.is-review .il-dd-sum-col.right {
        border-left: none;
        border-top: 1px solid #DCE3EA;
        margin-top: 12px;
        padding-top: 20px;
    }
    .il-dd-summary.is-review .il-dd-sum-col.left,
    .il-dd-summary.is-review .il-dd-sum-col.center,
    .il-dd-summary.is-review .il-dd-sum-col.right {
        align-items: center;
        text-align: center;
        padding-left: 0;
        padding-right: 0;
    }
    .il-dd-summary-left { border-right: none; padding-right: 0; border-bottom: 1px solid #DCE3EA; padding-bottom: 18px; margin-bottom: 18px; }
    .il-dd-committed { grid-template-columns: 1fr; gap: 14px; }
    .il-dd-committed-mid { border: none; padding: 0; }
    .il-dd-committed-right { padding-left: 0; }
    .il-decision-hero-action { text-align: left; font-size: var(--type-section); }
}
.il-decision-header {
    margin: 0 0 14px 0;
    padding: 4px 0 10px 0;
    border-bottom: 1px solid var(--line);
    text-align: left;
}
.il-decision-product {
    font-size: var(--type-section);
    font-weight: var(--weight-section);
    color: var(--navy);
    letter-spacing: -0.02em;
    margin: 0 0 8px 0;
}
.il-decision-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    color: var(--ink-2);
    font-size: var(--type-caption);
}
.il-decision-meta b { color: var(--ink); font-weight: 600; }
.il-stop-banner {
    background: var(--crit-soft, #FAEAE8);
    border: 1px solid #EFC9C4;
    color: var(--crit, #C0392B);
    border-radius: 8px;
    padding: 10px 12px;
    font-weight: 600;
    margin: 0 0 12px 0;
    text-align: left;
}
.il-step-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin: 0 0 14px 0;
}
.il-step-strip-item {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    text-align: left;
}
.il-step-name {
    font-size: var(--type-caption);
    font-weight: 600;
    color: var(--ink-2);
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.il-step-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 26px;
    padding: 2px 10px;
    border-radius: 6px;
    font-size: var(--type-caption);
    font-weight: 600;
    width: fit-content;
}
.il-step-badge.pass { background: #E6F3EE; color: #1E7A5A; border: 1px solid #BFDFD2; }
.il-step-badge.stop { background: #FAEAE8; color: #C0392B; border: 1px solid #EFC9C4; }
.il-step-badge.warn { background: #FBF1DE; color: #9A6410; border: 1px solid #E8D5A8; }
.il-step-badge.skip { background: #F1F4F7; color: #7A8896; border: 1px solid #E3E8ED; }
.il-evidence-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px 16px;
    text-align: left;
}
.il-evidence-row {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 0;
    border-bottom: 1px solid var(--line);
}
.il-evidence-row .lab {
    font-size: var(--type-caption);
    color: var(--ink-2);
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.il-evidence-row .val {
    font-size: var(--type-body);
    font-weight: 600;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
}
.il-guard-table { width: 100%; text-align: left; }
.il-guard-head, .il-guard-row {
    display: grid;
    grid-template-columns: 1.4fr 1fr 1fr 0.7fr 0.9fr;
    gap: 8px;
    padding: 8px 4px;
    align-items: center;
}
.il-guard-head {
    font-size: var(--type-table-head);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--ink-2);
    border-bottom: 1px solid var(--line);
    font-weight: 600;
}
.il-guard-row {
    border-bottom: 1px solid var(--line);
    font-size: var(--type-table);
}
@media (max-width: 900px) {
    .il-step-strip { grid-template-columns: 1fr 1fr; }
    .il-evidence-grid { grid-template-columns: 1fr; }
    .il-guard-head, .il-guard-row { grid-template-columns: 1fr 1fr; }
}

/* Buttons + focus (keyboard usability) */
div[data-testid="stButton"] button,
div[data-testid="stFormSubmitButton"] button {
    font-size: var(--type-body) !important;
    min-height: 36px !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}
div[data-testid="stButton"] button:focus-visible,
div[data-testid="stFormSubmitButton"] button:focus-visible,
div[data-testid="stTextInput"] input:focus-visible,
div[data-testid="stSelectbox"] div[data-baseweb="select"]:focus-within {
    outline: 2px solid var(--navy) !important;
    outline-offset: 2px !important;
}
div[data-testid="stButton"] button[kind="primary"],
div[data-testid="stFormSubmitButton"] button {
    background: var(--navy) !important;
    color: #FFFFFF !important;
    border: 1px solid var(--navy) !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover,
div[data-testid="stFormSubmitButton"] button:hover {
    background: #243a4e !important;
}
div[data-testid="stButton"] button[kind="secondary"] {
    background: var(--card) !important;
    color: var(--ink) !important;
    border: 1px solid var(--line) !important;
}

/* Delivery Details panel — header row + close × only */
div[class*="st-key-delivery_side_panel"] div[data-testid="stHorizontalBlock"]:has(.delivery-details-title) {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    justify-content: space-between !important;
    position: relative !important;
    width: 100% !important;
    margin: 0 0 16px 0 !important;
    padding: 0 44px 0 0 !important;
    box-sizing: border-box !important;
    gap: 8px !important;
}
div[class*="st-key-delivery_side_panel"] div[data-testid="stHorizontalBlock"]:has(.delivery-details-title) > [data-testid="stColumn"]:first-child {
    flex: 1 1 auto !important;
    width: auto !important;
    min-width: 0 !important;
    max-width: none !important;
}
div[class*="st-key-delivery_side_panel"] div[data-testid="stHorizontalBlock"]:has(.delivery-details-title) > [data-testid="stColumn"]:last-child {
    position: absolute !important;
    top: 0 !important;
    right: 0 !important;
    left: auto !important;
    flex: 0 0 40px !important;
    width: 40px !important;
    min-width: 40px !important;
    max-width: 40px !important;
    height: auto !important;
    overflow: visible !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 3 !important;
    display: flex !important;
    justify-content: flex-end !important;
    align-items: flex-start !important;
}
div[class*="st-key-delivery_side_panel"] div[data-testid="stHorizontalBlock"]:has(.delivery-details-title) [class*="st-key-close_delivery_"] {
    position: relative !important;
    top: auto !important;
    right: auto !important;
    left: auto !important;
    width: 40px !important;
    min-width: 40px !important;
    max-width: 40px !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 4 !important;
}
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] {
    margin: 0 0 0 auto !important;
    width: auto !important;
    min-width: 40px !important;
}
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button,
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button:hover,
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button:focus,
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button:active {
    width: auto !important;
    height: auto !important;
    min-width: 40px !important;
    min-height: auto !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #111827 !important;
    font-size: 24px !important;
    font-weight: 400 !important;
    padding: 0 !important;
    cursor: pointer !important;
}
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button p,
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button span,
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button div[data-testid="stMarkdownContainer"] p,
div[class*="st-key-close_delivery_"] div[data-testid="stButton"] button * {
    font-size: 24px !important;
    font-weight: 400 !important;
    color: #111827 !important;
    margin: 0 !important;
    line-height: 1 !important;
}

/* Delivery Details invoice input — suppress Streamlit dirty-state UI only here */
div[class*="st-key-delivery_invoice_input_"] [data-testid="InputInstructions"] {
    display: none !important;
}
div[class*="st-key-delivery_invoice_input_"] [data-testid="stTextInput"] input {
    border: 1px solid #E5E7EB !important;
    box-shadow: none !important;
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

/* —— Summary analytics page —— */
.il-sum-sec {
    margin: 28px 0 12px 0;
}
.il-sum-sec-title {
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    color: var(--navy);
    line-height: 1.3;
}
.il-sum-sec-sub {
    margin: 4px 0 0 0;
    font-size: 13px;
    color: var(--ink-3);
}
.il-sum-card {
    background: #fff;
    border: 1px solid #DCE3EA;
    border-radius: 12px;
    padding: 16px 18px;
    box-sizing: border-box;
}
.il-sum-empty {
    background: #fff;
    border: 1px dashed #DCE3EA;
    border-radius: 10px;
    padding: 18px;
    color: var(--ink-2);
    font-size: 14px;
}
.il-sum-muted {
    margin-top: 8px;
    font-size: 12px;
    color: var(--ink-3);
}
.il-sum-stack {
    display: flex;
    width: 100%;
    height: 18px;
    border-radius: 9px;
    overflow: hidden;
    background: #EEF2F5;
}
.il-sum-stack-seg { min-width: 0; }
.il-sum-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    margin-top: 12px;
}
.il-sum-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--ink-2);
}
.il-sum-legend-item .swatch {
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex: 0 0 auto;
}
.il-sum-hbar-row {
    display: grid;
    grid-template-columns: 90px 1fr 70px;
    gap: 10px;
    align-items: center;
    margin: 8px 0;
}
.il-sum-hbar-row .lab {
    font-size: 12px;
    color: var(--ink-2);
    font-weight: 600;
}
.il-sum-hbar-row .track {
    height: 10px;
    background: #EEF2F5;
    border-radius: 6px;
    overflow: hidden;
}
.il-sum-hbar-row .fill {
    height: 100%;
    background: #b91c1c;
    border-radius: 6px;
}
.il-sum-hbar-row .val {
    font-size: 12px;
    font-weight: 600;
    color: var(--ink);
    text-align: right;
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
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
    }
}
@media (max-width: 700px) {
    .il-kpi-row { grid-template-columns: 1fr; }
    [data-testid="stExpandSidebarButton"],
    button[data-testid="stExpandSidebarButton"] {
        display: none !important;
        visibility: hidden !important;
    }
}

/* Blocked detail page */
.il-blk-stack {
    display: flex;
    flex-direction: column;
    gap: 22px;
    margin: 8px 0 24px 0;
}
.il-blk-main-card,
.il-blk-card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 22px 24px;
    box-sizing: border-box;
}
.il-blk-header {
    margin-bottom: 20px;
}
.il-blk-title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
}
.il-blk-product {
    margin: 0;
    font-size: 30px;
    font-weight: 700;
    line-height: 1.15;
    color: var(--navy);
    letter-spacing: -0.02em;
}
.il-blk-badge {
    display: inline-flex;
    align-items: center;
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--status-critical-bg);
    color: var(--status-critical);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    white-space: nowrap;
}
.il-blk-meta {
    margin-top: 10px;
    font-size: 14px;
    line-height: 1.45;
    color: var(--ink-2);
}
.il-blk-warning {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 0;
    align-items: stretch;
    background: #FFF8F0;
    border: 1px solid #F3D9B5;
    border-radius: 10px;
    overflow: hidden;
}
.il-blk-warning-col {
    padding: 18px 20px;
    min-width: 0;
}
.il-blk-warning-divider {
    width: 1px;
    background: #F0D4B0;
    align-self: stretch;
}
.il-blk-warning-head {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 8px;
}
.il-blk-warning-head.is-why {
    color: #B45309;
}
.il-blk-warning-head.is-action {
    color: var(--status-progress);
}
.il-blk-warning-body {
    font-size: 15px;
    line-height: 1.45;
    color: var(--navy);
    font-weight: 500;
}
.il-blk-card-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--navy);
    margin-bottom: 4px;
}
.il-blk-details-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0 32px;
}
.il-blk-details-col {
    min-width: 0;
}
.il-blk-detail-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
    padding: 15px 0;
    border-bottom: 1px solid var(--line);
}
.il-blk-detail-row:last-child {
    border-bottom: none;
}
.il-blk-detail-label {
    font-size: 14px;
    color: var(--ink-2);
    flex: 1 1 auto;
}
.il-blk-detail-value {
    font-size: 14px;
    font-weight: 600;
    color: var(--navy);
    text-align: right;
    flex: 0 1 auto;
    max-width: 58%;
    word-break: break-word;
}
.il-blk-card-chart {
    padding-bottom: 18px;
}
.il-blk-stack [data-testid="stPlotlyChart"] {
    margin-top: 4px;
}
.il-blk-stack [data-testid="stPlotlyChart"] > div {
    border-radius: 8px;
}
.il-blk-chart-caption {
    margin: 8px 0 0 0;
    text-align: center;
    font-size: 12px;
    color: var(--ink-3);
}
.il-blk-chart-empty {
    margin: 12px 0 0 0;
    font-size: 13px;
    color: var(--ink-3);
    text-align: center;
}
@media (max-width: 900px) {
    .il-blk-warning {
        grid-template-columns: 1fr;
    }
    .il-blk-warning-divider {
        width: auto;
        height: 1px;
    }
    .il-blk-details-grid {
        grid-template-columns: 1fr;
        gap: 0;
    }
}

/* Handled automatically detail page */
.il-auto-page a[href^="#"],
.il-auto-page [data-testid="stHeaderActionElements"] {
    display: none !important;
}
.il-auto-stack {
    display: flex;
    flex-direction: column;
    gap: 22px;
    margin: 8px 0 24px 0;
}
.il-auto-main-card,
.il-auto-card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 22px 24px;
    box-sizing: border-box;
}
.il-auto-header {
    margin-bottom: 18px;
}
.il-auto-title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
}
.il-auto-product {
    margin: 0;
    font-size: 30px;
    font-weight: 700;
    line-height: 1.15;
    color: var(--navy);
    letter-spacing: -0.02em;
}
.il-auto-badge {
    display: inline-flex;
    align-items: center;
    padding: 6px 12px;
    border-radius: 999px;
    background: var(--status-success-bg);
    color: var(--status-success);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.01em;
    white-space: nowrap;
    text-align: center;
}
.il-auto-badge.is-neutral {
    background: var(--status-neutral-bg);
    color: var(--status-neutral);
}
.il-auto-meta {
    margin-top: 10px;
    font-size: 14px;
    line-height: 1.45;
    color: var(--ink-2);
}
.il-auto-summary {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100%;
    gap: 0;
    align-items: start;
    background: #FFFFFF;
    border: 1px solid #DCE3EA;
    border-radius: 10px;
    margin-bottom: 20px;
    overflow: hidden;
}
.il-auto-summary-col {
    padding: 20px 22px;
    min-width: 0;
}
.il-auto-summary-col.is-why-col {
    border-left: 1px solid #DCE3EA;
}
.il-auto-summary-head {
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    margin: 0;
    color: var(--navy);
}
.il-auto-summary-head.is-action {
    color: var(--status-success);
}
.il-auto-summary-head.is-why {
    color: var(--status-progress);
}
.il-auto-summary-body {
    margin-top: 10px;
    font-size: 15px;
    line-height: 1.45;
    color: var(--navy);
    font-weight: 500;
}
.il-auto-summary-body strong {
    font-weight: 700;
}
.il-auto-decision-panel {
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 18px 20px 8px 20px;
    background: #fff;
}
.il-auto-decision-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--navy);
    margin-bottom: 6px;
}
.il-auto-details-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0 32px;
}
.il-auto-details-col {
    min-width: 0;
}
.il-auto-detail-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
    padding: 15px 0;
    border-bottom: 1px solid var(--line);
}
.il-auto-detail-row:last-child {
    border-bottom: none;
}
.il-auto-detail-label {
    font-size: 14px;
    color: var(--ink-2);
    flex: 1 1 auto;
}
.il-auto-detail-value {
    font-size: 14px;
    font-weight: 600;
    color: var(--navy);
    text-align: right;
    flex: 0 1 auto;
    max-width: 58%;
    word-break: break-word;
}
.il-auto-card-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--navy);
    margin: 0;
    padding-top: 2px;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-auto_sales_"]) {
    background: var(--card) !important;
    border: 1px solid var(--line) !important;
    border-radius: 12px !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has([class*="st-key-auto_sales_"]) > div {
    gap: 0 !important;
    padding: 22px 24px !important;
}
[class*="st-key-auto_sales_"] [data-testid="stHorizontalBlock"]:first-of-type {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    width: 100% !important;
    margin: 0 0 16px 0 !important;
    gap: 12px !important;
}
[class*="st-key-auto_sales_"] [data-testid="stHorizontalBlock"]:first-of-type [data-testid="stColumn"] {
    display: flex !important;
    align-items: center !important;
    min-height: 0 !important;
}
[class*="st-key-auto_sales_"] [data-testid="stHorizontalBlock"]:first-of-type [data-testid="stColumn"]:last-child {
    justify-content: flex-end !important;
}
[class*="st-key-auto_sales_"] [data-testid="stHorizontalBlock"]:first-of-type [data-testid="stElementContainer"],
[class*="st-key-auto_sales_"] [data-testid="stHorizontalBlock"]:first-of-type [data-testid="element-container"] {
    margin: 0 !important;
    padding: 0 !important;
}
[class*="st-key-auto_sales_"] [data-testid="stRadio"] {
    margin: 0 !important;
}
[class*="st-key-auto_sales_"] [data-testid="stRadio"] > div {
    gap: 0 !important;
    background: var(--subtle);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 2px;
}
[class*="st-key-auto_sales_"] [data-testid="stRadio"] label {
    margin: 0 !important;
    padding: 6px 14px !important;
    border-radius: 6px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    color: var(--ink-2) !important;
}
[class*="st-key-auto_sales_"] [data-testid="stRadio"] label[data-checked="true"],
[class*="st-key-auto_sales_"] [data-testid="stRadio"] label:has(input:checked) {
    background: #fff !important;
    color: var(--navy) !important;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
}
[class*="st-key-auto_sales_"] [data-testid="stRadio"] input {
    display: none;
}
[class*="st-key-auto_sales_"] [data-testid="stPlotlyChart"] {
    margin-top: 0 !important;
}
.il-auto-chart-caption {
    margin: 8px 0 0 0;
    text-align: center;
    font-size: 12px;
    color: var(--ink-3);
}
.il-auto-chart-empty {
    margin: 0;
    font-size: 13px;
    color: var(--ink-3);
    text-align: center;
}
.il-auto-sales-table-wrap {
    max-width: 650px;
    width: 100%;
    margin-top: 0;
}
.il-auto-sales-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    background: #fff;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    overflow: hidden;
    font-size: 14px;
    line-height: 1.25;
}
.il-auto-sales-table th {
    height: 36px;
    min-height: 36px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 600;
    color: var(--ink-2);
    text-align: left;
    border-bottom: 1px solid #E2E8F0;
    background: #fff;
    vertical-align: middle;
}
.il-auto-sales-table th:first-child {
    width: 70%;
}
.il-auto-sales-table th:last-child {
    width: 30%;
    text-align: right;
}
.il-auto-sales-table td {
    height: 34px;
    min-height: 34px;
    padding: 7px 12px;
    color: var(--navy);
    text-align: left;
    border-bottom: 1px solid #EEF1F5;
    vertical-align: middle;
}
.il-auto-sales-table td:first-child {
    width: 70%;
}
.il-auto-sales-table td:last-child {
    width: 30%;
    text-align: right;
}
.il-auto-sales-table tbody tr:last-child td {
    border-bottom: none;
}
.il-auto-stack [data-testid="stPlotlyChart"] {
    margin-top: 8px;
}
.il-auto-stack div[data-testid="stButton"] {
    margin-top: 2px;
}
@media (max-width: 700px) {
    .il-auto-summary {
        grid-template-columns: 1fr !important;
    }
    .il-auto-summary-col.is-why-col {
        border-left: none;
        border-top: 1px solid #DCE3EA;
    }
}
@media (max-width: 900px) {
    .il-auto-details-grid {
        grid-template-columns: 1fr;
        gap: 0;
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
