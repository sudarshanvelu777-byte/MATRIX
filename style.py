"""
style.py
---------
Premium navy / white / grey theme, Times New Roman typography, used across
every screen (login, demo, authenticated trading view).
"""

THEME_CSS = """
<style>
:root{
    --navy-950:#060c1c;
    --navy-900:#0a1530;
    --navy-800:#101e42;
    --navy-700:#16295a;
    --navy-accent:#2d4a8a;
    --grey-100:#f4f5f7;
    --grey-300:#cfd3da;
    --grey-500:#9aa0ad;
    --grey-700:#5b6170;
    --white:#ffffff;
}

html, body, [class*="css"]  {
    font-family: "Times New Roman", Times, Georgia, serif !important;
}

.stApp {
    background: radial-gradient(1200px 600px at 10% -10%, var(--navy-800) 0%, var(--navy-950) 55%, #04070f 100%);
    color: var(--grey-100);
}

/* Header / hero */
.of-hero {
    padding: 2.2rem 2.4rem;
    border-radius: 18px;
    background: linear-gradient(135deg, var(--navy-900) 0%, var(--navy-700) 100%);
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 20px 50px rgba(0,0,0,0.45);
    margin-bottom: 1.6rem;
}
.of-hero h1 {
    color: var(--white);
    font-size: 2.3rem;
    letter-spacing: 0.5px;
    margin-bottom: 0.2rem;
    font-weight: 700;
}
.of-hero p {
    color: var(--grey-300);
    font-size: 1.05rem;
    margin: 0;
}

/* Premium card */
.of-card {
    background: linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.01) 100%);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 16px;
    padding: 1.4rem 1.6rem;
    box-shadow: 0 10px 30px rgba(0,0,0,0.35);
    margin-bottom: 1.1rem;
}
.of-card h3, .of-card h4 {
    color: var(--white);
    margin-top: 0;
}
.of-label {
    color: var(--grey-500);
    font-size: 0.82rem;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}

/* Pills / badges */
.of-pill {
    display: inline-block;
    padding: 0.22rem 0.8rem;
    border-radius: 999px;
    font-size: 0.78rem;
    letter-spacing: 1px;
    text-transform: uppercase;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    color: var(--grey-100);
}
.of-pill-demo { background: rgba(154,160,173,0.18); border-color: rgba(154,160,173,0.4); }
.of-pill-live { background: rgba(45,74,138,0.35); border-color: rgba(100,140,230,0.5); }

/* Buy / sell accents (kept monochrome-premium: white = buy, grey = sell) */
.of-buy  { color:#e7ecf7; font-weight:700; }
.of-sell { color:#b9c0cf; font-weight:700; }

/* Inbox preview (simulated email) */
.of-inbox {
    background: var(--grey-100);
    color: #10131a;
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
    border: 1px solid rgba(0,0,0,0.08);
}
.of-inbox .subject { font-weight:700; font-size:1.05rem; margin-bottom:0.4rem; }
.of-inbox .code {
    display:inline-block; margin-top:0.5rem; padding:0.4rem 0.9rem;
    background: var(--navy-900); color:#fff; border-radius:8px;
    font-size:1.3rem; letter-spacing:4px; font-weight:700;
}

hr.of-sep { border: none; border-top: 1px solid rgba(255,255,255,0.12); margin: 1.1rem 0; }

/* Make Streamlit's own buttons match the theme */
div.stButton > button {
    font-family: "Times New Roman", Times, serif !important;
    background: linear-gradient(135deg, var(--navy-700), var(--navy-accent));
    color: var(--white);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 10px;
    padding: 0.5rem 1.1rem;
}
div.stButton > button:hover {
    border-color: rgba(255,255,255,0.45);
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--navy-950), #03050a);
    border-right: 1px solid rgba(255,255,255,0.08);
}
</style>
"""


def inject(st):
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def hero(st, title, subtitle):
    st.markdown(
        f"""<div class="of-hero"><h1>{title}</h1><p>{subtitle}</p></div>""",
        unsafe_allow_html=True,
    )


def card_open(st, label=None):
    st.markdown(
        f"""<div class="of-card">{f'<div class="of-label">{label}</div>' if label else ''}""",
        unsafe_allow_html=True,
    )


def card_close(st):
    st.markdown("</div>", unsafe_allow_html=True)
