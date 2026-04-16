"""
start.py — One-shot setup for Verda.
Run this ONCE before starting the server:

    python start.py

It will:
  1. Clean up all unnecessary files
  2. Set up / migrate the database
  3. Register all 10 products on the blockchain (skip if already registered)
  4. Generate QR codes for each product
  5. Print instructions to start the server
"""
import os
import shutil
import sqlite3
import json
import hashlib
import qrcode
from datetime import datetime

BASE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'products.db')
QR_DIR  = os.path.join(BASE, 'static', 'qrcodes')
os.makedirs(QR_DIR, exist_ok=True)

# ── 1. CLEANUP ─────────────────────────────────────────────────────────
JUNK_FILES = [
    "90DAY_EXECUTION_CHECKLIST.md",
    "BUSINESS_STRATEGY_FUNDRAISING.md",
    "DELIVERY_SUMMARY.md",
    "FIRST_48_HOURS.md",
    "INDEX.md",
    "PHASE1_IMPLEMENTATION_GUIDE.md",
    "README_OVERVIEW.md",
    "TECHNICAL_DEEP_DIVE.md",
    "VERDA_STARTUP_ROADMAP.md",
    "blockchain_explorer.html",
    os.path.join("templates", "scan.html"),
    os.path.join("templates", "test_qr.html"),
    "setup_db.py",
    "generate_qr.py",
    "cleanup.py",
]
JUNK_DIRS = ["__pycache__", ".venv-1", "venv"]

def cleanup():
    print("\n🧹 Step 1: Cleanup")
    removed = 0
    for f in JUNK_FILES:
        p = os.path.join(BASE, f)
        if os.path.isfile(p):
            os.remove(p)
            print(f"   🗑  {f}")
            removed += 1
    for d in JUNK_DIRS:
        p = os.path.join(BASE, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            print(f"   🗑  {d}/")
            removed += 1
    print(f"   ✅ {removed} items removed")

# ── 2. DATABASE SETUP ─────────────────────────────────────────────────
def setup_db(conn):
    print("\n🗄  Step 2: Database")
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
            idx           INTEGER PRIMARY KEY,
            product_id    TEXT,
            product_data  TEXT,
            previous_hash TEXT,
            block_hash    TEXT,
            timestamp     TEXT
        )
    ''')
    # Add image column if missing (migration)
    try:
        conn.execute("ALTER TABLE products ADD COLUMN image TEXT")
    except Exception:
        pass
    conn.commit()
    print("   ✅ Tables ready")

# ── 3 & 4. BLOCKCHAIN + QR ────────────────────────────────────────────
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

QR_BASE_URL = "http://127.0.0.1:5000"

def calc_hash(index, product_id, product_data, previous_hash, timestamp):
    s = json.dumps({
        "index": index, "timestamp": timestamp,
        "product_id": product_id, "product_data": product_data,
        "previous_hash": previous_hash
    }, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()

def ensure_genesis(conn):
    if conn.execute("SELECT COUNT(*) FROM blockchain").fetchone()[0] == 0:
        ts   = datetime.now().isoformat()
        data = {"info": "Verda Genesis Block — Chain Initialized"}
        h    = calc_hash(0, "GENESIS", data, "0", ts)
        conn.execute(
            "INSERT INTO blockchain VALUES (?,?,?,?,?,?)",
            (0, "GENESIS", json.dumps(data), "0", h, ts)
        )
        conn.commit()

def seed_products(conn):
    print("\n⛓  Step 3: Registering products")
    ensure_genesis(conn)

    for pid, name, category in PRODUCTS:
        # Insert into products table
        try:
            conn.execute(
                "INSERT INTO products (product_id, name, category) VALUES (?,?,?)",
                (pid, name, category)
            )
            conn.commit()
            db_status = "added"
        except Exception:
            db_status = "exists"

        # Blockchain
        bc_exists = conn.execute(
            "SELECT COUNT(*) FROM blockchain WHERE product_id=?", (pid,)
        ).fetchone()[0]
        if not bc_exists:
            last = conn.execute(
                "SELECT block_hash, idx FROM blockchain ORDER BY idx DESC LIMIT 1"
            ).fetchone()
            idx  = last[1] + 1
            prev = last[0]
            ts   = datetime.now().isoformat()
            pdata = {"name": name, "category": category, "registered": ts}
            h    = calc_hash(idx, pid, pdata, prev, ts)
            conn.execute(
                "INSERT INTO blockchain VALUES (?,?,?,?,?,?)",
                (idx, pid, json.dumps(pdata), prev, h, ts)
            )
            conn.commit()
            bc_status = "registered"
        else:
            bc_status = "exists"

        # QR code
        qr_path = os.path.join(QR_DIR, f"{pid}.png")
        if not os.path.exists(qr_path):
            url = f"{QR_BASE_URL}/scan/{pid}"
            img = qrcode.make(url)
            img.save(qr_path)
            qr_status = "generated"
        else:
            qr_status = "exists"

        icon = "✅" if bc_status == "registered" else "⏭ "
        print(f"   {icon} {pid}  DB:{db_status}  BC:{bc_status}  QR:{qr_status}")

    chain_len = conn.execute("SELECT COUNT(*) FROM blockchain").fetchone()[0]
    print(f"\n   ⛓  Blockchain: {chain_len} blocks total")

# ── MAIN ───────────────────────────────────────────────────────────────
def main():
    print("=" * 52)
    print("  Verda — Setup & Seed")
    print("=" * 52)

    cleanup()

    conn = sqlite3.connect(DB_PATH)
    setup_db(conn)
    seed_products(conn)
    conn.close()

    print("\n" + "=" * 52)
    print("  ✅ All done! Next steps:")
    print("─" * 52)
    print("  1. Start the server:")
    print("     python app.py")
    print()
    print("  2. Open in browser:")
    print(f"     {QR_BASE_URL}")
    print()
    print("  3. Test image upload:")
    print(f"     {QR_BASE_URL}/upload-scan")
    print("=" * 52 + "\n")

if __name__ == '__main__':
    main()
