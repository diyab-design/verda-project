"""
seed.py — Run this once to set up the database, register all products
on the blockchain, and generate QR codes for each product.

Usage:  python seed.py
"""
import sqlite3
import os
import sys
import json
import hashlib
import qrcode
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'products.db')
QR_DIR  = os.path.join(BASE, 'static', 'qrcodes')
os.makedirs(QR_DIR, exist_ok=True)

# ── Products to seed ───────────────────────────────────────────────────
PRODUCTS = [
    ("VERDA001", "Eco Soap",               "Personal Care"),
    ("VERDA002", "Bamboo Toothbrush",      "Oral Care"),
    ("VERDA003", "Organic Shampoo",        "Hair Care"),
    ("VERDA004", "Reusable Bottle",        "Lifestyle"),
    ("VERDA005", "Herbal Face Wash",       "Skincare"),
    ("VERDA006", "Natural Lip Balm",       "Skincare"),
    ("VERDA007", "Compostable Trash Bags", "Household"),
    ("VERDA008", "Organic Body Lotion",    "Skincare"),
    ("VERDA009", "Bamboo Cutlery Set",     "Lifestyle"),
    ("VERDA010", "Reusable Grocery Bag",   "Lifestyle"),
]

# Base URL used in QR codes — change this to your server's IP if needed
QR_BASE_URL = "http://127.0.0.1:5000"

# ── DB setup ───────────────────────────────────────────────────────────
def setup_db(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT    UNIQUE NOT NULL,
            name       TEXT    NOT NULL,
            category   TEXT    NOT NULL,
            image      TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT    NOT NULL,
            timestamp  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS blockchain (
            idx          INTEGER PRIMARY KEY,
            product_id   TEXT,
            product_data TEXT,
            previous_hash TEXT,
            block_hash   TEXT,
            timestamp    TEXT
        )
    ''')
    conn.commit()
    print("✅ Tables created / verified")


# ── Blockchain helpers (mirrors blockchain.py logic) ───────────────────
def calc_hash(index, product_id, product_data, previous_hash, timestamp):
    block_string = json.dumps({
        "index":        index,
        "timestamp":    timestamp,
        "product_id":   product_id,
        "product_data": product_data,
        "previous_hash": previous_hash
    }, sort_keys=True)
    return hashlib.sha256(block_string.encode()).hexdigest()


def ensure_genesis(conn):
    count = conn.execute("SELECT COUNT(*) FROM blockchain").fetchone()[0]
    if count == 0:
        ts   = datetime.now().isoformat()
        data = {"info": "Verda Genesis Block — Chain Initialized"}
        h    = calc_hash(0, "GENESIS", data, "0", ts)
        conn.execute(
            "INSERT INTO blockchain (idx,product_id,product_data,previous_hash,block_hash,timestamp) VALUES (?,?,?,?,?,?)",
            (0, "GENESIS", json.dumps(data), "0", h, ts)
        )
        conn.commit()
        print("🔗 Genesis block created")


def register_on_blockchain(conn, product_id, product_data):
    exists = conn.execute(
        "SELECT COUNT(*) FROM blockchain WHERE product_id=?", (product_id,)
    ).fetchone()[0]
    if exists:
        return False  # already registered

    last = conn.execute(
        "SELECT block_hash, idx FROM blockchain ORDER BY idx DESC LIMIT 1"
    ).fetchone()
    prev_hash = last[0]
    index     = last[1] + 1
    ts        = datetime.now().isoformat()

    h = calc_hash(index, product_id, product_data, prev_hash, ts)
    conn.execute(
        "INSERT INTO blockchain (idx,product_id,product_data,previous_hash,block_hash,timestamp) VALUES (?,?,?,?,?,?)",
        (index, product_id, json.dumps(product_data), prev_hash, h, ts)
    )
    conn.commit()
    return True


# ── QR code generator ──────────────────────────────────────────────────
def make_qr(product_id):
    url  = f"{QR_BASE_URL}/scan/{product_id}"
    path = os.path.join(QR_DIR, f"{product_id}.png")
    if not os.path.exists(path):
        img = qrcode.make(url)
        img.save(path)
        return True
    return False   # already exists


# ── Main ───────────────────────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print(f"\n{'='*50}")
    print(" Verda — Seed Script")
    print(f"{'='*50}\n")

    setup_db(conn)
    ensure_genesis(conn)

    new_products   = 0
    new_blockchain = 0
    new_qr         = 0
    skipped        = 0

    for pid, name, category in PRODUCTS:
        # 1. Insert into products table
        try:
            conn.execute(
                "INSERT INTO products (product_id, name, category) VALUES (?,?,?)",
                (pid, name, category)
            )
            conn.commit()
            new_products += 1
        except sqlite3.IntegrityError:
            skipped += 1  # already exists

        # 2. Register on blockchain
        product_data = {
            "name":       name,
            "category":   category,
            "registered": datetime.now().isoformat()
        }
        added = register_on_blockchain(conn, pid, product_data)
        if added:
            new_blockchain += 1

        # 3. Generate QR code
        made = make_qr(pid)
        if made:
            new_qr += 1

        status_sym = "🆕" if (skipped == 0 or new_products > 0) else "⏭"
        print(f"  {pid}  →  DB {'added' if new_products else 'exists'}  |  "
              f"Blockchain {'registered' if added else 'exists'}  |  "
              f"QR {'generated' if made else 'exists'}")

    conn.close()

    print(f"\n{'─'*50}")
    print(f"  New DB rows:    {new_products}")
    print(f"  New BC blocks:  {new_blockchain}")
    print(f"  New QR codes:   {new_qr}")
    print(f"  Already exists: {skipped}")
    print(f"{'─'*50}\n")
    print("✅ Done! Restart the Flask server and visit http://127.0.0.1:5000")


if __name__ == '__main__':
    main()
