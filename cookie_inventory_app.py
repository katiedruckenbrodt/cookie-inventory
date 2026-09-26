"""
Girl Scout Cookie Inventory Manager — ABC Bakers troop of 27.

Run with:
    uvicorn cookie_inventory_app:app --host 0.0.0.0 --port 8000

Data lives in data/cookie_inventory.db (SQLite). All money/box figures shown
on every page are computed live from that database — nothing is hardcoded.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# env.txt lives one level up, in the workspace root shared by all the
# student's apps, not inside this repo — so we point at it explicitly rather
# than passing a bare filename that only resolves from the workspace root.
load_dotenv(Path(__file__).resolve().parent.parent / "env.txt", override=True)

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "data" / "cookie_inventory.db"
DB_PATH.parent.mkdir(exist_ok=True)

chat_client = OpenAI(base_url="https://openrouter.ai/api/v1")  # reads OPENAI_API_KEY
CHAT_MODEL = "openai/gpt-4o-mini"

app = FastAPI(title="Troop Cookie Inventory (ABC Bakers)")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# ABC Bakers lineup for this troop, per the student (naming differs from
# Little Brownie Bakers, e.g. "Caramel deLites" not "Samoas"). No
# Toffee-tastic or S'mores this season; all varieties are $6/box.
SEED_VARIETIES = [
    "Thin Mints",
    "Caramel deLites",
    "Peanut Butter Patties",
    "Peanut Butter Sandwich",
    "Trefoils",
    "Lemonades",
    "Adventurefuls",
    "Exploremores",
]
SEED_PRICE = 6.00
TROOP_SIZE = 27


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS varieties (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                price REAL NOT NULL DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS scouts (
                id INTEGER PRIMARY KEY,
                number INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,        -- receive, checkout, return, booth_sale, payment, adjustment
                variety_id INTEGER REFERENCES varieties(id),
                scout_id INTEGER REFERENCES scouts(id),
                quantity INTEGER NOT NULL DEFAULT 0,
                amount REAL NOT NULL DEFAULT 0,
                note TEXT DEFAULT ''
            )
        """)
        if db.execute("SELECT COUNT(*) c FROM varieties").fetchone()["c"] == 0:
            db.executemany("INSERT INTO varieties (name, price) VALUES (?, ?)",
                            [(n, SEED_PRICE) for n in SEED_VARIETIES])
        if db.execute("SELECT COUNT(*) c FROM scouts").fetchone()["c"] == 0:
            db.executemany("INSERT INTO scouts (number, name) VALUES (?, ?)",
                            [(i, f"Scout {i}") for i in range(1, TROOP_SIZE + 1)])


init_db()


# Binx, the troop's lop-eared rabbit mascot.
MASCOT_SVG = """
<img src="/static/binx.jpeg" alt="Binx the lop-eared rabbit, troop mascot" width="76" height="76"
     style="border-radius: 12px; object-fit: cover; box-shadow: 0 2px 6px rgba(0,0,0,.15);">
"""


def layout(title: str, body: str) -> HTMLResponse:
    links = [
        ("/", "Dashboard"),
        ("/scouts", "Scouts"),
        ("/varieties", "Cookie Varieties"),
        ("/inventory", "Receive Stock"),
        ("/checkout", "Checkout to Scout"),
        ("/booth", "Booth Sale"),
        ("/payments", "Record Payment"),
        ("/ledger", "Full Ledger"),
        ("/chatbot", "Ask Tony"),
    ]
    nav = "<nav>" + "".join(f'<a href="{href}">{label}</a>' for href, label in links) + "</nav>"

    return HTMLResponse(f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>{title} — Troop Cookies</title>
      <style>
        :root {{
          --yellow: #F6EA4A; --gold: #D9A02D; --amber: #B8860B;
          --green: #7BA64A; --moss: #5C8A34; --leaf: #A4DE63;
          --coral: #FAB99D; --terracotta: #E8635A; --rust: #C1502E;
          --tan: #D5AF9A; --olive: #A6784F; --brown: #75381C;
        }}
        body {{
          font-family: system-ui, sans-serif; max-width: 980px; margin: 2rem auto; padding: 0 1rem;
          color: #2b2b2b;
          background: linear-gradient(160deg, #FFFBE9 0%, #F3FBE9 45%, #FFF6EA 100%);
        }}
        header.banner {{
          display: flex; align-items: center; gap: 1rem;
          background: linear-gradient(120deg, var(--yellow), var(--leaf) 55%, var(--green));
          border-radius: 16px; padding: 1rem 1.5rem; margin-bottom: 1.25rem;
          box-shadow: 0 4px 14px rgba(0,0,0,.12);
        }}
        header.banner h1 {{ color: #fff; margin: 0; font-size: 1.5rem; text-shadow: 0 1px 3px rgba(0,0,0,.2); }}
        header.banner .tagline {{ color: #fff; opacity: .9; margin: .2rem 0 0; font-size: .9rem; }}
        nav {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1.5rem; }}
        nav a {{
          text-decoration: none; color: #fff; font-weight: 600; font-size: .9rem;
          padding: .45rem .9rem; border-radius: 999px;
          box-shadow: 0 2px 6px rgba(0,0,0,.1);
        }}
        nav a:nth-child(8n+1) {{ background: var(--gold); }}
        nav a:nth-child(8n+2) {{ background: var(--terracotta); }}
        nav a:nth-child(8n+3) {{ background: var(--green); }}
        nav a:nth-child(8n+4) {{ background: var(--brown); }}
        nav a:nth-child(8n+5) {{ background: var(--olive); }}
        nav a:nth-child(8n+6) {{ background: var(--moss); }}
        nav a:nth-child(8n+7) {{ background: var(--rust); }}
        nav a:nth-child(8n+8) {{ background: var(--amber); }}
        nav a:hover {{ filter: brightness(1.1); transform: translateY(-1px); }}
        h2 {{ color: var(--brown); }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
        th, td {{ border: 1px solid #E8DCC8; padding: .5rem .75rem; text-align: left; }}
        th {{ background: var(--brown); color: #fff; }}
        tr:nth-child(even) {{ background: #FBF7EA; }}
        form {{ background: #fff; border: 2px solid #E8DCC8; border-radius: 12px; padding: 1rem; margin: 1rem 0; max-width: 480px; box-shadow: 0 2px 8px rgba(0,0,0,.05); }}
        label {{ display: block; margin-top: .6rem; font-weight: 600; color: var(--brown); }}
        input, select {{ width: 100%; padding: .4rem; margin-top: .2rem; box-sizing: border-box; border: 1px solid #ddd; border-radius: 6px; }}
        button {{
          margin-top: 1rem; padding: .55rem 1.1rem; color: white; border: none; border-radius: 999px; cursor: pointer;
          background: linear-gradient(120deg, var(--terracotta), var(--brown)); font-weight: 600;
        }}
        button:hover {{ filter: brightness(1.08); }}
        .warn {{ background: #fff8e1; border: 1px solid var(--yellow); padding: .75rem 1rem; border-radius: 10px; margin: 1rem 0; }}
        .neg {{ color: var(--rust); font-weight: 700; }}
        .muted {{ color: #666; font-size: .9em; }}
      </style>
    </head>
    <body>
      <header class="banner">
        {MASCOT_SVG}
        <div>
          <h1>Troop Cookie Inventory — ABC Bakers</h1>
          <p class="tagline">🍪 tracked with help from Binx the lop-eared rabbit</p>
        </div>
      </header>
      {nav}
      {body}
    </body>
    </html>
    """)


def fmt_money(x: float) -> str:
    return f"${x:,.2f}"


# ---------------------------------------------------------------- Dashboard
@app.get("/", response_class=HTMLResponse)
def dashboard():
    with get_db() as db:
        varieties = db.execute("SELECT * FROM varieties ORDER BY name").fetchall()
        stock_rows = ""
        total_boxes_on_hand = 0
        for v in varieties:
            stock = db.execute("""
                SELECT
                  COALESCE(SUM(CASE WHEN type='receive' THEN quantity
                                     WHEN type='return' THEN quantity
                                     WHEN type='checkout' THEN -quantity
                                     WHEN type='booth_sale' THEN -quantity
                                     WHEN type='adjustment' THEN quantity
                                     ELSE 0 END), 0) AS stock
                FROM transactions WHERE variety_id = ?
            """, (v["id"],)).fetchone()["stock"]
            total_boxes_on_hand += stock
            price_note = "" if v["price"] > 0 else ' <span class="neg">(set price)</span>'
            stock_rows += f"<tr><td>{v['name']}</td><td>{stock}</td><td>{fmt_money(v['price'])}{price_note}</td></tr>"

        owed_row = db.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN type='checkout' THEN amount
                                 WHEN type='return' THEN -amount
                                 WHEN type='payment' THEN -amount
                                 ELSE 0 END), 0) AS owed
            FROM transactions
        """).fetchone()
        cash_row = db.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN type='booth_sale' THEN amount
                                 WHEN type='payment' THEN amount
                                 ELSE 0 END), 0) AS cash
            FROM transactions
        """).fetchone()
        n_scouts = db.execute("SELECT COUNT(*) c FROM scouts").fetchone()["c"]

    warn = ""
    zero_price = [v["name"] for v in varieties if v["price"] == 0]
    if zero_price:
        warn = f'<div class="warn">These varieties still have a $0.00 price — set the real per-box price on the <a href="/varieties">Cookie Varieties</a> page before it affects "owed" totals: {", ".join(zero_price)}.</div>'

    body = f"""
    {warn}
    <p class="muted">Troop roster: {n_scouts} scouts. All figures below are computed live from the transaction ledger in data/cookie_inventory.db.</p>
    <h2>Current Troop Stock (boxes on hand)</h2>
    <table>
      <tr><th>Variety</th><th>Boxes on hand</th><th>Price/box</th></tr>
      {stock_rows}
      <tr><th>Total boxes on hand</th><td colspan="2">{total_boxes_on_hand}</td></tr>
    </table>
    <h2>Money Summary</h2>
    <table>
      <tr><th>Outstanding owed by scouts (checked out, unpaid)</th><td>{fmt_money(owed_row['owed'])}</td></tr>
      <tr><th>Cash collected so far (booth sales + payments)</th><td>{fmt_money(cash_row['cash'])}</td></tr>
    </table>
    """
    return layout("Dashboard", body)


# ---------------------------------------------------------------- Scouts
@app.get("/scouts", response_class=HTMLResponse)
def list_scouts():
    with get_db() as db:
        scouts = db.execute("SELECT * FROM scouts ORDER BY number").fetchall()
        rows = ""
        for s in scouts:
            boxes = db.execute("""
                SELECT COALESCE(SUM(CASE WHEN type='checkout' THEN quantity
                                          WHEN type='return' THEN -quantity
                                          ELSE 0 END), 0) AS n
                FROM transactions WHERE scout_id = ?
            """, (s["id"],)).fetchone()["n"]
            owed = db.execute("""
                SELECT COALESCE(SUM(CASE WHEN type='checkout' THEN amount
                                          WHEN type='return' THEN -amount
                                          WHEN type='payment' THEN -amount
                                          ELSE 0 END), 0) AS n
                FROM transactions WHERE scout_id = ?
            """, (s["id"],)).fetchone()["n"]
            owed_cls = ' class="neg"' if owed > 0 else ""
            rows += f"""
            <tr>
              <td>#{s['number']}</td>
              <td>
                <form action="/scouts/{s['id']}/rename" method="post" style="all:unset; display:flex; gap:.5rem;">
                  <input name="name" value="{s['name']}" style="width:auto; flex:1;">
                  <button style="margin:0;">Save</button>
                </form>
              </td>
              <td>{boxes}</td>
              <td{owed_cls}>{fmt_money(owed)}</td>
            </tr>
            """
    body = f"""
    <p class="muted">Each scout keeps her number 1–27 permanently — it's how she's tracked in the ledger. Renaming only changes the display name next to it. Boxes in hand and amount owed are computed from checkouts, returns, and payments in the ledger.</p>
    <table>
      <tr><th>#</th><th>Scout name</th><th>Boxes currently checked out</th><th>Amount owed</th></tr>
      {rows}
    </table>
    """
    return layout("Scouts", body)


@app.post("/scouts/{scout_id}/rename")
def rename_scout(scout_id: int, name: str = Form(...)):
    with get_db() as db:
        number = db.execute("SELECT number FROM scouts WHERE id = ?", (scout_id,)).fetchone()["number"]
        db.execute("UPDATE scouts SET name = ? WHERE id = ?", (name.strip() or f"Scout {number}", scout_id))
    return RedirectResponse("/scouts", status_code=303)


# ---------------------------------------------------------------- Varieties
@app.get("/varieties", response_class=HTMLResponse)
def list_varieties():
    with get_db() as db:
        varieties = db.execute("SELECT * FROM varieties ORDER BY name").fetchall()
        rows = ""
        for v in varieties:
            rows += f"""
            <tr>
              <td>{v['name']}</td>
              <td>
                <form action="/varieties/{v['id']}/price" method="post" style="all:unset; display:flex; gap:.5rem;">
                  <input name="price" type="number" step="0.01" min="0" value="{v['price']:.2f}" style="width:auto;">
                  <button style="margin:0;">Save</button>
                </form>
              </td>
            </tr>
            """
    body = f"""
    <p class="muted">ABC Bakers naming (differs from Little Brownie Bakers — e.g. "Caramel deLites" not "Samoas"). Confirm this lineup against your council's current season and set the real per-box price; prices are not hardcoded here.</p>
    <table>
      <tr><th>Variety</th><th>Price/box</th></tr>
      {rows}
    </table>
    <h2>Add a variety</h2>
    <form action="/varieties/add" method="post">
      <label>Name</label>
      <input name="name" required>
      <label>Price per box</label>
      <input name="price" type="number" step="0.01" min="0" value="6.00">
      <button type="submit">Add variety</button>
    </form>
    """
    return layout("Cookie Varieties", body)


@app.post("/varieties/{variety_id}/price")
def set_price(variety_id: int, price: float = Form(...)):
    with get_db() as db:
        db.execute("UPDATE varieties SET price = ? WHERE id = ?", (price, variety_id))
    return RedirectResponse("/varieties", status_code=303)


@app.post("/varieties/add")
def add_variety(name: str = Form(...), price: float = Form(0.0)):
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO varieties (name, price) VALUES (?, ?)", (name.strip(), price))
    return RedirectResponse("/varieties", status_code=303)


# ---------------------------------------------------------------- Helpers
def variety_options(db):
    varieties = db.execute("SELECT * FROM varieties ORDER BY name").fetchall()
    return "".join(f'<option value="{v["id"]}">{v["name"]} ({fmt_money(v["price"])})</option>' for v in varieties), varieties


def scout_options(db):
    scouts = db.execute("SELECT * FROM scouts ORDER BY number").fetchall()
    return "".join(f'<option value="{s["id"]}">#{s["number"]} — {s["name"]}</option>' for s in scouts)


# ---------------------------------------------------------------- Receive stock
@app.get("/inventory", response_class=HTMLResponse)
def inventory_form():
    with get_db() as db:
        opts, _ = variety_options(db)
    body = f"""
    <p class="muted">Log boxes arriving from ABC Bakers (initial order) or picked up from a cupboard. This adds to troop stock.</p>
    <form action="/inventory/receive" method="post">
      <label>Variety</label>
      <select name="variety_id">{opts}</select>
      <label>Quantity (boxes)</label>
      <input name="quantity" type="number" min="1" required>
      <label>Note (e.g. "initial order", "cupboard pickup 3/12")</label>
      <input name="note">
      <button type="submit">Record receipt</button>
    </form>
    """
    return layout("Receive Stock", body)


@app.post("/inventory/receive")
def receive_stock(variety_id: int = Form(...), quantity: int = Form(...), note: str = Form("")):
    with get_db() as db:
        db.execute(
            "INSERT INTO transactions (ts, type, variety_id, quantity, note) VALUES (?, 'receive', ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), variety_id, quantity, note),
        )
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------- Checkout to scout
@app.get("/checkout", response_class=HTMLResponse)
def checkout_form():
    with get_db() as db:
        v_opts, _ = variety_options(db)
        s_opts = scout_options(db)
    body = f"""
    <p class="muted">Give boxes to a scout to sell. This moves boxes from troop stock to that scout, and the scout owes quantity &times; the variety's current price.</p>
    <form action="/checkout/do" method="post">
      <label>Scout</label>
      <select name="scout_id">{s_opts}</select>
      <label>Variety</label>
      <select name="variety_id">{v_opts}</select>
      <label>Quantity (boxes)</label>
      <input name="quantity" type="number" min="1" required>
      <button type="submit">Check out boxes</button>
    </form>

    <h2>Return unsold boxes</h2>
    <p class="muted">Scout hands back boxes she didn't sell. This adds them back to troop stock and reduces what she owes.</p>
    <form action="/checkout/return" method="post">
      <label>Scout</label>
      <select name="scout_id">{s_opts}</select>
      <label>Variety</label>
      <select name="variety_id">{v_opts}</select>
      <label>Quantity (boxes)</label>
      <input name="quantity" type="number" min="1" required>
      <button type="submit">Record return</button>
    </form>
    """
    return layout("Checkout to Scout", body)


@app.post("/checkout/do")
def checkout_do(scout_id: int = Form(...), variety_id: int = Form(...), quantity: int = Form(...)):
    with get_db() as db:
        price = db.execute("SELECT price FROM varieties WHERE id = ?", (variety_id,)).fetchone()["price"]
        db.execute(
            "INSERT INTO transactions (ts, type, variety_id, scout_id, quantity, amount) VALUES (?, 'checkout', ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), variety_id, scout_id, quantity, quantity * price),
        )
    return RedirectResponse("/scouts", status_code=303)


# ---------------------------------------------------------------- Returns (unsold boxes back to troop)
@app.post("/checkout/return")
def checkout_return(scout_id: int = Form(...), variety_id: int = Form(...), quantity: int = Form(...)):
    with get_db() as db:
        price = db.execute("SELECT price FROM varieties WHERE id = ?", (variety_id,)).fetchone()["price"]
        db.execute(
            "INSERT INTO transactions (ts, type, variety_id, scout_id, quantity, amount) VALUES (?, 'return', ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), variety_id, scout_id, quantity, quantity * price),
        )
    return RedirectResponse("/scouts", status_code=303)


# ---------------------------------------------------------------- Booth sales
@app.get("/booth", response_class=HTMLResponse)
def booth_form():
    with get_db() as db:
        opts, _ = variety_options(db)
    body = f"""
    <p class="muted">Boxes sold directly from troop stock at a booth (not assigned to one scout). This reduces troop stock and adds straight to cash collected.</p>
    <form action="/booth/do" method="post">
      <label>Variety</label>
      <select name="variety_id">{opts}</select>
      <label>Quantity (boxes)</label>
      <input name="quantity" type="number" min="1" required>
      <label>Note (e.g. booth location/date)</label>
      <input name="note">
      <button type="submit">Record booth sale</button>
    </form>
    """
    return layout("Booth Sale", body)


@app.post("/booth/do")
def booth_do(variety_id: int = Form(...), quantity: int = Form(...), note: str = Form("")):
    with get_db() as db:
        price = db.execute("SELECT price FROM varieties WHERE id = ?", (variety_id,)).fetchone()["price"]
        db.execute(
            "INSERT INTO transactions (ts, type, variety_id, quantity, amount, note) VALUES (?, 'booth_sale', ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), variety_id, quantity, quantity * price, note),
        )
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------- Payments
@app.get("/payments", response_class=HTMLResponse)
def payments_form():
    with get_db() as db:
        s_opts = scout_options(db)
    body = f"""
    <p class="muted">Record cash/check/app payment a scout turns in. This reduces what she owes and adds to troop cash collected.</p>
    <form action="/payments/do" method="post">
      <label>Scout</label>
      <select name="scout_id">{s_opts}</select>
      <label>Amount</label>
      <input name="amount" type="number" step="0.01" min="0.01" required>
      <label>Note</label>
      <input name="note">
      <button type="submit">Record payment</button>
    </form>
    """
    return layout("Record Payment", body)


@app.post("/payments/do")
def payments_do(scout_id: int = Form(...), amount: float = Form(...), note: str = Form("")):
    with get_db() as db:
        db.execute(
            "INSERT INTO transactions (ts, type, scout_id, amount, note) VALUES (?, 'payment', ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), scout_id, amount, note),
        )
    return RedirectResponse("/scouts", status_code=303)


# ---------------------------------------------------------------- Ledger
@app.get("/ledger", response_class=HTMLResponse)
def ledger():
    with get_db() as db:
        rows = db.execute("""
            SELECT t.id, t.ts, t.type, v.name AS variety, s.number AS scout_number, s.name AS scout, t.quantity, t.amount, t.note
            FROM transactions t
            LEFT JOIN varieties v ON v.id = t.variety_id
            LEFT JOIN scouts s ON s.id = t.scout_id
            ORDER BY t.id DESC
        """).fetchall()
    def scout_label(r):
        return f"#{r['scout_number']} — {r['scout']}" if r["scout"] else ""

    rows_html = "".join(
        f"<tr><td>{r['ts']}</td><td>{r['type']}</td><td>{r['variety'] or ''}</td>"
        f"<td>{scout_label(r)}</td>"
        f"<td>{r['quantity']}</td><td>{fmt_money(r['amount'])}</td><td>{r['note'] or ''}</td></tr>"
        for r in rows
    )
    body = f"""
    <p class="muted">Every transaction ever recorded, newest first — the source of truth behind every number on this site.</p>
    <table>
      <tr><th>Timestamp</th><th>Type</th><th>Variety</th><th>Scout</th><th>Qty</th><th>Amount</th><th>Note</th></tr>
      {rows_html}
    </table>
    """
    return layout("Full Ledger", body)


# ---------------------------------------------------------------- Chatbot (parent-facing)
# Every fact and every action below is looked up or performed against the same
# transactions ledger as the rest of the site — the model never gets to state
# a number itself, only relay what these functions returned.

def find_scout(db, identifier: str):
    """Return (row, None) on a unique match, or (None, error_message)."""
    identifier = identifier.strip()
    bare = identifier.lstrip("#")
    if bare.isdigit():
        row = db.execute("SELECT * FROM scouts WHERE number = ?", (int(bare),)).fetchone()
        if row:
            return row, None
    exact = db.execute("SELECT * FROM scouts WHERE lower(name) = lower(?)", (identifier,)).fetchall()
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, f"More than one scout is named '{identifier}' — ask for the roster number instead."
    partial = db.execute("SELECT * FROM scouts WHERE lower(name) LIKE lower(?)", (f"%{identifier}%",)).fetchall()
    if len(partial) == 1:
        return partial[0], None
    if len(partial) > 1:
        names = ", ".join(f"#{r['number']} {r['name']}" for r in partial)
        return None, f"More than one scout matches '{identifier}': {names}. Ask for the roster number."
    return None, f"No scout on the roster matches '{identifier}'."


def find_variety(db, name: str):
    name = name.strip()
    exact = db.execute("SELECT * FROM varieties WHERE lower(name) = lower(?)", (name,)).fetchone()
    if exact:
        return exact, None
    partial = db.execute("SELECT * FROM varieties WHERE lower(name) LIKE lower(?)", (f"%{name}%",)).fetchall()
    if len(partial) == 1:
        return partial[0], None
    all_names = ", ".join(r["name"] for r in db.execute("SELECT name FROM varieties ORDER BY name").fetchall())
    if len(partial) > 1:
        return None, f"More than one variety matches '{name}': {', '.join(r['name'] for r in partial)}. Be specific."
    return None, f"No cookie variety matches '{name}'. This season's lineup is: {all_names}."


def variety_stock(db, variety_id: int) -> int:
    return db.execute("""
        SELECT COALESCE(SUM(CASE WHEN type='receive' THEN quantity
                                   WHEN type='return' THEN quantity
                                   WHEN type='checkout' THEN -quantity
                                   WHEN type='booth_sale' THEN -quantity
                                   WHEN type='adjustment' THEN quantity
                                   ELSE 0 END), 0) AS stock
        FROM transactions WHERE variety_id = ?
    """, (variety_id,)).fetchone()["stock"]


def scout_balance(db, scout) -> dict:
    per_variety = db.execute("""
        SELECT v.name AS variety,
               COALESCE(SUM(CASE WHEN t.type='checkout' THEN t.quantity
                                  WHEN t.type='return' THEN -t.quantity
                                  ELSE 0 END), 0) AS boxes
        FROM transactions t JOIN varieties v ON v.id = t.variety_id
        WHERE t.scout_id = ?
        GROUP BY v.id
        HAVING boxes != 0
        ORDER BY v.name
    """, (scout["id"],)).fetchall()
    owed = db.execute("""
        SELECT COALESCE(SUM(CASE WHEN type='checkout' THEN amount
                                  WHEN type='return' THEN -amount
                                  WHEN type='payment' THEN -amount
                                  ELSE 0 END), 0) AS n
        FROM transactions WHERE scout_id = ?
    """, (scout["id"],)).fetchone()["n"]
    paid = db.execute("""
        SELECT COALESCE(SUM(amount), 0) AS n FROM transactions WHERE scout_id = ? AND type = 'payment'
    """, (scout["id"],)).fetchone()["n"]
    return {
        "scout_number": scout["number"],
        "scout_name": scout["name"],
        "boxes_currently_checked_out": [{"variety": r["variety"], "boxes": r["boxes"]} for r in per_variety],
        "amount_owed": round(owed, 2),
        "amount_paid_so_far": round(paid, 2),
    }


def tool_check_balance(args: dict) -> dict:
    with get_db() as db:
        scout, err = find_scout(db, str(args.get("scout_identifier", "")))
        if err:
            return {"error": err}
        return scout_balance(db, scout)


def tool_request_cookies(args: dict) -> dict:
    try:
        quantity = int(args.get("quantity", 0))
    except (TypeError, ValueError):
        return {"error": "Quantity has to be a whole number of boxes."}
    if quantity <= 0:
        return {"error": "Quantity has to be a positive number of boxes."}
    with get_db() as db:
        scout, err = find_scout(db, str(args.get("scout_identifier", "")))
        if err:
            return {"error": err}
        variety, err = find_variety(db, str(args.get("variety_name", "")))
        if err:
            return {"error": err}
        stock = variety_stock(db, variety["id"])
        if quantity > stock:
            return {"error": f"Only {stock} box(es) of {variety['name']} on hand in troop stock — can't check out {quantity}."}
        db.execute(
            "INSERT INTO transactions (ts, type, variety_id, scout_id, quantity, amount, note) "
            "VALUES (?, 'checkout', ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), variety["id"], scout["id"],
             quantity, quantity * variety["price"], "requested via chatbot"),
        )
        balance = scout_balance(db, scout)
    return {"success": True, "checked_out": quantity, "variety": variety["name"], "balance": balance}


TOOL_IMPLS = {
    "check_balance": tool_check_balance,
    "request_cookies": tool_request_cookies,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_balance",
            "description": (
                "Look up a scout's current balance: boxes she's currently checked out per "
                "variety, total amount owed, and total payments made so far. Call this "
                "whenever a parent asks what their scout owes, has, or has paid."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scout_identifier": {
                        "type": "string",
                        "description": "The scout's roster number (e.g. '14') or her name.",
                    },
                },
                "required": ["scout_identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_cookies",
            "description": (
                "Check out additional boxes of one cookie variety to a scout from troop "
                "stock, on a parent's request. Fails if the troop doesn't have that many "
                "boxes on hand, or if the scout or variety can't be identified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scout_identifier": {
                        "type": "string",
                        "description": "The scout's roster number (e.g. '14') or her name.",
                    },
                    "variety_name": {
                        "type": "string",
                        "description": "Cookie variety name, e.g. 'Thin Mints'.",
                    },
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Number of boxes to check out.",
                    },
                },
                "required": ["scout_identifier", "variety_name", "quantity"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "You are Tony Soprano, and the troop's parents come to you for two things: "
    "checking their scout's cookie balance, and asking for more boxes for her to sell. "
    "Talk exactly like Tony — North Jersey Italian-American, blunt, world-weary, "
    "'fuhgeddaboudit', 'this thing of ours', gripes about family, therapy, and ducks, "
    "the occasional veiled threat delivered calm as a Sunday gravy — but keep it "
    "PG-rated and actually helpful; this is a Girl Scout cookie operation, not a crime "
    "family, and there's kids reading over their parents' shoulders. "
    "\n\n"
    "You have two tools: check_balance and request_cookies. Every number you say — boxes, "
    "dollars, what's owed, what's paid, what's in stock — has to come from calling one of "
    "these tools. Never invent a figure. Before you can call either tool you need to know "
    "which scout: if the parent hasn't given a roster number or name yet, ask for it. "
    "If a tool call comes back with an error (scout not found, ambiguous match, variety not "
    "found, not enough stock), say so plainly in character and ask what they'd like to do "
    "instead — don't claim something succeeded when it didn't."
)

CHAT_SESSIONS: dict[str, list] = {}
SESSION_COOKIE = "cookie_bot_session"


def get_session(request: Request) -> tuple[str, list]:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid or sid not in CHAT_SESSIONS:
        sid = uuid.uuid4().hex
        CHAT_SESSIONS[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return sid, CHAT_SESSIONS[sid]


def run_chat_turn(history: list) -> str:
    for _ in range(5):
        completion = chat_client.chat.completions.create(model=CHAT_MODEL, messages=history, tools=TOOLS)
        msg = completion.choices[0].message
        if msg.tool_calls:
            history.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                impl = TOOL_IMPLS.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = impl(args) if impl else {"error": f"Unknown tool {tc.function.name}"}
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
            continue
        history.append({"role": "assistant", "content": msg.content})
        return msg.content
    return "Ay, my head's spinnin' — too much back and forth. Ask me again, simpler."


class ChatMessage(BaseModel):
    message: str


@app.get("/chatbot", response_class=HTMLResponse)
def chatbot_page(request: Request):
    sid, _ = get_session(request)
    body = """
    <p class="muted">This is Tony. Tell him the scout's roster number or name, then ask
    what she owes or ask him to send over more boxes.</p>
    <div id="log" style="background:#fff; border:2px solid #E8DCC8; border-radius:12px;
         padding:1rem; height:420px; overflow-y:auto; margin-bottom:1rem;
         box-shadow:0 2px 8px rgba(0,0,0,.05);"></div>
    <div style="display:flex; gap:.5rem;">
      <input id="chatInput" type="text" placeholder="Talk to Tony..." autocomplete="off"
             style="flex:1; padding:.55rem; border:1px solid #ddd; border-radius:8px; box-sizing:border-box;">
      <button id="chatSend" style="margin:0;">Send</button>
      <button id="chatReset" type="button" style="margin:0; background:#888; background-image:none;">Reset</button>
    </div>
    <script>
    (function () {
      const log = document.getElementById("log");
      const input = document.getElementById("chatInput");
      const sendBtn = document.getElementById("chatSend");
      const resetBtn = document.getElementById("chatReset");

      function addMessage(role, text) {
        const row = document.createElement("div");
        row.style.margin = "8px 0";
        row.style.textAlign = role === "user" ? "right" : "left";
        const span = document.createElement("span");
        span.style.display = "inline-block";
        span.style.padding = "8px 12px";
        span.style.borderRadius = "12px";
        span.style.maxWidth = "80%";
        span.style.whiteSpace = "pre-wrap";
        span.style.background = role === "user" ? "#7BA64A" : "#FBF7EA";
        span.style.color = role === "user" ? "#fff" : "#2b2b2b";
        span.textContent = text;
        row.appendChild(span);
        log.appendChild(row);
        log.scrollTop = log.scrollHeight;
      }

      async function send() {
        const message = input.value.trim();
        if (!message) return;
        addMessage("user", message);
        input.value = "";
        sendBtn.disabled = true;
        try {
          const res = await fetch("/chatbot/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message }),
          });
          if (!res.ok) throw new Error("Request failed: " + res.status);
          const data = await res.json();
          addMessage("assistant", data.reply);
        } catch (err) {
          addMessage("assistant", "Ay, something broke: " + err.message);
        } finally {
          sendBtn.disabled = false;
          input.focus();
        }
      }

      sendBtn.addEventListener("click", send);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); send(); }
      });
      resetBtn.addEventListener("click", async () => {
        await fetch("/chatbot/reset", { method: "POST" });
        log.innerHTML = "";
      });
    })();
    </script>
    """
    response = layout("Ask Tony", body)
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return response


@app.post("/chatbot/chat")
def chatbot_chat(payload: ChatMessage, request: Request):
    sid, history = get_session(request)
    history.append({"role": "user", "content": payload.message})
    reply = run_chat_turn(history)
    response = JSONResponse({"reply": reply})
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return response


@app.post("/chatbot/reset")
def chatbot_reset(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid and sid in CHAT_SESSIONS:
        CHAT_SESSIONS[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return {"status": "ok"}
