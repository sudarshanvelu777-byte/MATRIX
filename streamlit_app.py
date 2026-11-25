"""
streamlit_app.py
------------------
Stock Market Order Matching Engine -- Streamlit front end.

Backend by design:
  - All order-matching logic (priority queues, FIFO per-price queues, the
    matching loop, the order index, the event log) lives in pure C --
    see engine/orderbook.c -- and is reached only through engine_bridge.py
    (ctypes). Streamlit never matches an order itself.
  - User accounts / verification codes / order & trade history live in
    SQLite, opened in WAL mode -- see db.py.
  - System resource metrics ("performance counters" in the UI) come from
    psutil.

Run with:   streamlit run app/streamlit_app.py
"""

import psutil
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib

matplotlib.use("Agg")

import db
import mailer
import ipo_data
import style
from engine_bridge import OrderBookEngine, SIDE_BUY, SIDE_SELL

# --------------------------------------------------------------------- #
# Page config + theme + db init
# --------------------------------------------------------------------- #

st.set_page_config(page_title="OrderFlow Markets", page_icon="\u265c", layout="wide")
style.inject(st)
db.init_db()

# --------------------------------------------------------------------- #
# Session-state defaults
# --------------------------------------------------------------------- #

defaults = {
    "auth_stage": "login",      # login -> password | verify_code -> new_user_details -> done
    "pending_email": "",
    "pending_username": "",
    "authenticated": False,
    "demo_mode": False,
    "user": None,                # dict from db.get_user_by_email
    "engines": {},                # symbol -> OrderBookEngine
    "selected_symbol": "NEXORA",
    "ipo_query": "",
    "last_error": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


def logout():
    for k, v in defaults.items():
        st.session_state[k] = v


# --------------------------------------------------------------------- #
# Engine helpers (one C order book per traded symbol, cached in session)
# --------------------------------------------------------------------- #

def get_engine(symbol: str) -> OrderBookEngine:
    if symbol not in st.session_state.engines:
        eng = OrderBookEngine()
        for o in ipo_data.generate_synthetic_order_flow(symbol, n_orders=40):
            side = SIDE_BUY if o["side"] == "BUY" else SIDE_SELL
            if o["type"] == "MARKET":
                eng.add_market(side, o["qty"])
            else:
                eng.add_limit(side, o["price"], o["qty"])
        st.session_state.engines[symbol] = eng
    return st.session_state.engines[symbol]


# --------------------------------------------------------------------- #
# Auth screens
# --------------------------------------------------------------------- #

def screen_login():
    style.hero(
        st,
        "OrderFlow Markets",
        "A premium, price-time-priority order matching engine &mdash; C core, Streamlit desk.",
    )
    col1, col2 = st.columns([1.3, 1])

    with col1:
        style.card_open(st, "Sign in or create an account")
        with st.form("email_form"):
            email = st.text_input("Email address", placeholder="you@example.com")
            submitted = st.form_submit_button("Continue")
        if submitted:
            if "@" not in email or "." not in email.split("@")[-1]:
                st.error("Please enter a valid email address.")
            else:
                existing = db.get_user_by_email(email)
                st.session_state.pending_email = email
                if existing:
                    st.session_state.auth_stage = "password"
                else:
                    code = db.issue_verification_code(email)
                    result = mailer.send_verification_email(email, code)
                    st.session_state.mail_result = result
                    st.session_state.auth_stage = "verify_code"
                st.rerun()
        style.card_close(st)

    with col2:
        style.card_open(st, "No account needed")
        st.markdown(
            "<h4>Try the Demo Account</h4>"
            "<p style='color:var(--grey-300)'>Browse IPOs, live charts and the order "
            "book instantly. Placing or cancelling orders requires a free account.</p>",
            unsafe_allow_html=True,
        )
        if st.button("Continue with Demo Account", use_container_width=True):
            st.session_state.demo_mode = True
            st.rerun()
        style.card_close(st)


def screen_password():
    style.hero(st, "Welcome back", f"This email is already registered &mdash; sign in to continue.")
    style.card_open(st)
    st.markdown(
        f"<span class='of-pill of-pill-live'>Existing account</span>"
        f"&nbsp;&nbsp;<b>{st.session_state.pending_email}</b> already has an OrderFlow account.",
        unsafe_allow_html=True,
    )
    with st.form("password_form"):
        pw = st.text_input("Password", type="password")
        c1, c2 = st.columns(2)
        submit = c1.form_submit_button("Log in")
        back = c2.form_submit_button("Use a different email")
    if back:
        st.session_state.auth_stage = "login"
        st.rerun()
    if submit:
        user = db.authenticate(st.session_state.pending_email, pw)
        if user:
            st.session_state.user = user
            st.session_state.authenticated = True
            st.session_state.auth_stage = "done"
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
    style.card_close(st)


def screen_verify_code():
    style.hero(st, "Verify your email", "We've sent a 6-digit verification code.")
    style.card_open(st)

    result = st.session_state.get("mail_result", {})
    if result.get("mode") == "smtp":
        st.success(f"A verification email has been sent to {st.session_state.pending_email}.")
    else:
        # No outbound network/SMTP in this environment -> show a realistic
        # "inbox preview" instead of silently failing the login flow.
        msg = mailer.get_last_sim_message(st.session_state.pending_email) or {}
        st.markdown(
            f"""<div class="of-inbox">
                    <div class="subject">{msg.get('subject', 'Welcome to OrderFlow Markets - verify your email')}</div>
                    <div>Hello, welcome to OrderFlow Markets! We're excited to have you.</div>
                    <div class="code">{result.get('code','------')}</div>
                    <div style="margin-top:0.6rem;font-size:0.85rem;color:#555;">
                        Inbox preview &mdash; this sandbox has no outbound network access, so the
                        code is shown here instead of being delivered by real SMTP. Set
                        SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM as
                        environment variables to send a real email in a deployed copy of this app.
                    </div>
                </div>""",
            unsafe_allow_html=True,
        )

    with st.form("code_form"):
        code = st.text_input("Enter the 6-digit code", max_chars=6)
        c1, c2, c3 = st.columns(3)
        submit = c1.form_submit_button("Verify")
        resend = c2.form_submit_button("Resend code")
        back = c3.form_submit_button("Back")
    if back:
        st.session_state.auth_stage = "login"
        st.rerun()
    if resend:
        new_code = db.issue_verification_code(st.session_state.pending_email)
        st.session_state.mail_result = mailer.send_verification_email(
            st.session_state.pending_email, new_code
        )
        st.rerun()
    if submit:
        if db.check_verification_code(st.session_state.pending_email, code):
            st.session_state.auth_stage = "new_user_details"
            st.rerun()
        else:
            st.error("That code is incorrect or has expired. Try again or resend.")
    style.card_close(st)


def screen_new_user_details():
    style.hero(st, "Create your account", "Email verified &mdash; choose a username and password.")
    style.card_open(st)
    with st.form("newuser_form"):
        username = st.text_input("Username")
        pw1 = st.text_input("Password", type="password")
        pw2 = st.text_input("Confirm password", type="password")
        submit = st.form_submit_button("Create account & log in")
    if submit:
        if len(username.strip()) < 3:
            st.error("Username must be at least 3 characters.")
        elif len(pw1) < 6:
            st.error("Password must be at least 6 characters.")
        elif pw1 != pw2:
            st.error("Passwords do not match.")
        else:
            try:
                db.create_user(st.session_state.pending_email, username, pw1)
                user = db.authenticate(st.session_state.pending_email, pw1)
                st.session_state.user = user
                st.session_state.authenticated = True
                st.session_state.auth_stage = "done"
                st.rerun()
            except Exception as e:
                st.error(f"That username may already be taken. ({e})")
    style.card_close(st)


# --------------------------------------------------------------------- #
# Main trading dashboard (demo + authenticated share this view)
# --------------------------------------------------------------------- #

SIDE_COLORS = {"BUY": "#e9c46a", "SELL": "#4fb6a8"}  # unique accent palette for charts


def render_ipo_search():
    style.card_open(st, "IPO / market search")
    query = st.text_input("Search by ticker, company or sector", value=st.session_state.ipo_query,
                           placeholder="e.g. NEXORA, biotech, energy")
    st.session_state.ipo_query = query
    results = ipo_data.search_ipo(query)
    if not results:
        st.info("No matching listings.")
    else:
        cols = st.columns(min(5, len(results)) or 1)
        for i, row in enumerate(results):
            with cols[i % len(cols)]:
                selected = row["symbol"] == st.session_state.selected_symbol
                check_mark = "\u2713 " if selected else ""
                label = f"{check_mark}{row['symbol']}"
                if st.button(label, key=f"ipo_{row['symbol']}", use_container_width=True):
                    st.session_state.selected_symbol = row["symbol"]
                    st.rerun()
                st.caption(f"{row['name']}  \u00b7  {row['sector']}  \u00b7  IPO ${row['ipo_price']:.2f}")
    style.card_close(st)


def render_price_chart(symbol):
    history = ipo_data.generate_price_history(symbol, points=60)
    prices = [h["price"] for h in history]

    fig, ax = plt.subplots(figsize=(7, 3), facecolor="#0a1530")
    ax.set_facecolor("#0a1530")
    ax.plot(range(len(prices)), prices, color="#e9c46a", linewidth=2.2)
    ax.fill_between(range(len(prices)), prices, min(prices), color="#e9c46a", alpha=0.08)
    ax.set_title(f"{symbol} \u2014 synthetic price history", color="white", fontsize=11, fontfamily="serif")
    ax.tick_params(colors="#9aa0ad", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#2d4a8a")
    ax.grid(alpha=0.12, color="#9aa0ad")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)
    return prices


def render_order_entry(symbol, can_trade):
    style.card_open(st, "Place an order \u2014 Order Matching Engine")
    if not can_trade:
        st.warning("You're in the **Demo Account**. Please log in or create a free account to "
                   "submit orders to the live matching engine.")
    with st.form("order_form"):
        c1, c2, c3, c4 = st.columns(4)
        side = c1.selectbox("Side", ["BUY", "SELL"])
        otype = c2.selectbox("Type", ["LIMIT", "MARKET"])
        price = c3.number_input("Price", min_value=0.01, value=100.00, step=0.05, disabled=(otype == "MARKET"))
        qty = c4.number_input("Quantity", min_value=1, value=10, step=1)
        submitted = st.form_submit_button("Submit order", use_container_width=True)

    if submitted:
        if not can_trade:
            st.error("Demo accounts cannot place orders. Please log in or sign up above.")
        else:
            eng = get_engine(symbol)
            before = eng.trade_count()
            side_const = SIDE_BUY if side == "BUY" else SIDE_SELL
            if otype == "MARKET":
                oid = eng.add_market(side_const, int(qty))
                db.log_order(st.session_state.user["id"], symbol, side, otype, None, int(qty))
            else:
                oid = eng.add_limit(side_const, float(price), int(qty))
                db.log_order(st.session_state.user["id"], symbol, side, otype, float(price), int(qty))

            after = eng.trade_count()
            new_trades = eng.trades()[before:after]
            for t in new_trades:
                db.log_trade(st.session_state.user["id"], symbol, t["price"], t["qty"])

            if new_trades:
                st.success(f"Order #{oid} accepted \u2014 {len(new_trades)} trade(s) executed immediately.")
            else:
                st.info(f"Order #{oid} accepted and resting in the book.")

    with st.expander("Cancel an existing order by ID"):
        cid = st.number_input("Order ID to cancel", min_value=1, value=1, step=1, key="cancel_id")
        if st.button("Cancel order"):
            if not can_trade:
                st.error("Demo accounts cannot cancel orders. Please log in or sign up above.")
            else:
                eng = get_engine(symbol)
                ok = eng.cancel(int(cid))
                st.success(f"Order #{cid} cancelled.") if ok else st.warning(f"Order #{cid} not found (already filled or invalid).")
    style.card_close(st)


def render_book_and_tape(symbol):
    eng = get_engine(symbol)
    book = eng.book(depth=10)
    trades = eng.trades()[-15:][::-1]

    c1, c2 = st.columns(2)
    with c1:
        style.card_open(st, "Order book depth (price-time priority)")
        bid_rows = book["bids"] or [{"price": "-", "qty": "-", "orders": "-"}]
        ask_rows = book["asks"] or [{"price": "-", "qty": "-", "orders": "-"}]
        st.markdown("**Bids (buy side)**")
        st.table([{"Price": r["price"], "Qty": r["qty"], "Orders": r["orders"]} for r in bid_rows])
        st.markdown("**Asks (sell side)**")
        st.table([{"Price": r["price"], "Qty": r["qty"], "Orders": r["orders"]} for r in ask_rows])
        style.card_close(st)

    with c2:
        style.card_open(st, "Trade tape (most recent first)")
        if trades:
            st.table([
                {"Trade #": t["trade_id"], "Buy order": t["buy_id"], "Sell order": t["sell_id"],
                 "Price": t["price"], "Qty": t["qty"]}
                for t in trades
            ])
        else:
            st.info("No trades yet for this symbol.")
        style.card_close(st)


def render_charts(symbol):
    eng = get_engine(symbol)
    trades = eng.trades()

    c1, c2 = st.columns(2)

    with c1:
        style.card_open(st, "Order history \u2014 side distribution")
        book = eng.book(depth=50)
        buy_qty = sum(r["qty"] for r in book["bids"])
        sell_qty = sum(r["qty"] for r in book["asks"])
        if buy_qty + sell_qty == 0:
            st.info("No resting liquidity to chart yet.")
        else:
            fig, ax = plt.subplots(figsize=(4, 4), facecolor="#0a1530")
            wedges, _, autotexts = ax.pie(
                [buy_qty, sell_qty],
                labels=["Resting buys", "Resting sells"],
                colors=["#e9c46a", "#4fb6a8"],
                autopct="%1.0f%%",
                textprops={"color": "white", "fontfamily": "serif"},
                wedgeprops={"linewidth": 1.5, "edgecolor": "#0a1530"},
            )
            ax.set_title(f"{symbol} resting order volume", color="white", fontfamily="serif")
            fig.patch.set_facecolor("#0a1530")
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        style.card_close(st)

    with c2:
        style.card_open(st, "Trade price over sequence")
        if trades:
            prices = [t["price"] for t in trades]
            fig, ax = plt.subplots(figsize=(4, 4), facecolor="#0a1530")
            ax.set_facecolor("#0a1530")
            ax.plot(range(len(prices)), prices, color="#c084fc", marker="o", markersize=3, linewidth=1.6)
            ax.set_title(f"{symbol} executed trade prices", color="white", fontsize=10, fontfamily="serif")
            ax.tick_params(colors="#9aa0ad", labelsize=8)
            for spine in ax.spines.values():
                spine.set_color("#2d4a8a")
            ax.grid(alpha=0.12, color="#9aa0ad")
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        else:
            st.info("No executed trades yet \u2014 submit a crossing order to see this chart populate.")
        style.card_close(st)


def render_event_log(symbol):
    eng = get_engine(symbol)
    with st.expander("Engine event log (accept / trade / cancel audit trail)"):
        events = eng.events(max_n=40)
        if events:
            st.table([{"Seq": e["seq"], "Type": e["type"], "Detail": e["detail"]} for e in reversed(events)])
        else:
            st.caption("No events yet.")


def render_performance_counters(symbol):
    eng = get_engine(symbol)
    style.card_open(st, "Performance counters")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CPU usage", f"{psutil.cpu_percent(interval=0.05):.1f}%")
    c2.metric("Memory usage", f"{psutil.virtual_memory().percent:.1f}%")
    c3.metric("Trades executed", eng.trade_count())
    c4.metric("Events logged", eng.event_count())
    style.card_close(st)


def render_dashboard():
    can_trade = st.session_state.authenticated and not st.session_state.demo_mode
    badge = "<span class='of-pill of-pill-live'>Live account</span>" if can_trade else \
            "<span class='of-pill of-pill-demo'>Demo account</span>"
    name = st.session_state.user["username"] if can_trade else "Guest"

    with st.sidebar:
        st.markdown(f"### OrderFlow Markets")
        st.markdown(badge, unsafe_allow_html=True)
        st.markdown(f"**{name}**")
        st.markdown("<hr class='of-sep'>", unsafe_allow_html=True)
        if st.button("Log out", use_container_width=True):
            logout()
            st.rerun()

    style.hero(
        st,
        f"{st.session_state.selected_symbol} \u2014 live order book",
        "Bid/ask priority queues, per-price FIFO matching and a full audit trail, all computed in C.",
    )
    st.markdown(badge, unsafe_allow_html=True)
    st.write("")

    render_ipo_search()
    render_price_chart(st.session_state.selected_symbol)
    render_order_entry(st.session_state.selected_symbol, can_trade)
    render_book_and_tape(st.session_state.selected_symbol)
    render_charts(st.session_state.selected_symbol)
    render_performance_counters(st.session_state.selected_symbol)
    render_event_log(st.session_state.selected_symbol)


# --------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------- #

if st.session_state.demo_mode or st.session_state.authenticated:
    render_dashboard()
elif st.session_state.auth_stage == "password":
    screen_password()
elif st.session_state.auth_stage == "verify_code":
    screen_verify_code()
elif st.session_state.auth_stage == "new_user_details":
    screen_new_user_details()
else:
    screen_login()
