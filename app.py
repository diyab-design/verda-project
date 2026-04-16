from flask import Flask, render_template, redirect, make_response, session, request
import sqlite3
from datetime import datetime, timedelta
import os
import csv
import io
import json
from fpdf import FPDF
import qrcode
import uuid
from werkzeug.utils import secure_filename
from blockchain import Blockchain

app = Flask(__name__)
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'products.db')
app.secret_key = 'verda2026'

UPLOAD_FOLDER = os.path.join('static', 'product_images')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

blockchain = Blockchain(os.path.join(os.path.dirname(__file__), 'products.db'))

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'verda123'

def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def check_authenticity(product_id):
    conn = get_db()

    # Factor 1: Full blockchain verification (hash check + exists)
    bc_details = blockchain.get_verification_details(product_id)
    bc_valid, bc_result = blockchain.verify_product(product_id)

    if not bc_valid:
        conn.close()
        return None, "Fake", f"❌ Not registered on blockchain: {bc_result}", bc_details

    # Factor 2: Does product exist in DB?
    product = conn.execute(
        "SELECT * FROM products WHERE product_id=?", (product_id,)
    ).fetchone()
    if not product:
        conn.close()
        return None, "Fake", "Product not found in database", bc_details

    # Factor 3-5: Velocity checks
    velocity = blockchain.get_scan_velocity(product_id, db_conn=conn)
    conn.close()

    total  = velocity["total"]
    recent = velocity["last_hour"]
    rapid  = velocity["last_5min"]
    score  = velocity["threat_score"]

    if score == 0:
        return product, "Authentic", f"✅ Verified on blockchain — block #{bc_details['block_index']}", bc_details
    elif score <= 3:
        return product, "Suspicious", f"⚠️ Unusual pattern: {recent} scans/hr, {rapid} in last 5 min", bc_details
    else:
        return product, "Fake", f"❌ High-frequency attack: {rapid} scans in 5 min — possible counterfeit QR", bc_details

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/camera')
def camera():
    response = make_response(render_template('camera.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@app.route('/upload-scan')
def upload_scan():
    """QR image upload & blockchain verification page."""
    response = make_response(render_template('upload_scan.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@app.route('/scan/<product_id>')
def scan(product_id):
    conn = get_db()
    conn.execute("INSERT INTO scans (product_id) VALUES (?)", (product_id,))
    conn.commit()
    conn.close()
    product, status, reason, bc_details = check_authenticity(product_id)
    return render_template('result.html', product=product, status=status,
                           pid=product_id, reason=reason, bc=bc_details)


@app.route('/api/verify/<product_id>')
def api_verify(product_id):
    """JSON endpoint for real-time blockchain verification."""
    bc_valid, bc_result = blockchain.verify_product(product_id)
    bc_details = blockchain.get_verification_details(product_id)
    conn = get_db()
    velocity = blockchain.get_scan_velocity(product_id, db_conn=conn)
    product = conn.execute(
        "SELECT * FROM products WHERE product_id=?", (product_id,)
    ).fetchone()
    conn.close()
    return json.dumps({
        "product_id": product_id,
        "blockchain_valid": bc_valid,
        "in_database": product is not None,
        "block_index": bc_details.get("block_index"),
        "block_hash": bc_details.get("block_hash"),
        "registered_at": bc_details.get("registered_at"),
        "velocity": velocity,
        "chain_valid": bc_details.get("chain_valid"),
        "message": bc_result
    }), 200, {'Content-Type': 'application/json'}

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USERNAME and \
           request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/admin')
        else:
            error = 'Invalid credentials. Try again.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

@app.route('/admin')
def admin():
    if not session.get('logged_in'):
        return redirect('/login')
    conn = get_db()
    products = conn.execute("SELECT * FROM products").fetchall()
    scans = conn.execute(
        "SELECT product_id, COUNT(*) as count FROM scans GROUP BY product_id"
    ).fetchall()
    conn.close()
    return render_template('admin.html', products=products, scans=scans)

@app.route('/add-product', methods=['GET', 'POST'])
def add_product():
    if not session.get('logged_in'):
        return redirect('/login')

    if request.method == 'POST':
        product_id = request.form['product_id'].upper().strip()
        name = request.form['name'].strip()
        category = request.form['category'].strip()
        brand = request.form.get('brand', '').strip()
        image_filename = None

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                image_filename = f"{product_id}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO products (product_id, name, category, image) VALUES (?,?,?,?)",
                (product_id, name, category, image_filename)
            )
            conn.commit()
        except:
            conn.close()
            return render_template('add_product.html', error="Product ID already exists!")
        conn.close()

        # Register on blockchain
        product_data = {
            "name": name,
            "category": category,
            "brand": brand,
            "registered": datetime.now().isoformat()
        }
        blockchain.add_product(product_id, product_data)

        # Generate QR code
        qr_folder = os.path.join(os.path.dirname(__file__), 'static', 'qrcodes')
        os.makedirs(qr_folder, exist_ok=True)
        url = f"http://192.168.137.1:5000/scan/{product_id}"
        img = qrcode.make(url)
        img.save(os.path.join(qr_folder, f"{product_id}.png"))

        return redirect('/admin')

    return render_template('add_product.html')

@app.route('/blockchain')
def blockchain_explorer():
    if not session.get('logged_in'):
        return redirect('/login')
    chain = blockchain.get_full_chain()
    is_valid = blockchain.is_chain_valid()
    stats = blockchain.get_stats()
    return render_template('blockchain_explorer.html', chain=chain,
                           is_valid=is_valid, stats=stats)

@app.route('/export')
def export():
    if not session.get('logged_in'):
        return redirect('/login')
    conn = get_db()
    scans = conn.execute("SELECT * FROM scans").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Product ID', 'Timestamp'])
    for scan in scans:
        writer.writerow([scan['id'], scan['product_id'], scan['timestamp']])
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=scan_logs.csv'
    response.headers['Content-type'] = 'text/csv'
    return response

@app.route('/chart-data')
def chart_data():
    conn = get_db()
    scans = conn.execute(
        "SELECT product_id, COUNT(*) as count FROM scans GROUP BY product_id"
    ).fetchall()
    conn.close()
    labels = [s['product_id'] for s in scans]
    values = [s['count'] for s in scans]
    return json.dumps({'labels': labels, 'values': values})

@app.route('/print-qr')
def print_qr():
    if not session.get('logged_in'):
        return redirect('/login')
    products = [
        ("VERDA001", "Eco Soap"),
        ("VERDA002", "Bamboo Toothbrush"),
        ("VERDA003", "Organic Shampoo"),
        ("VERDA004", "Reusable Bottle"),
        ("VERDA005", "Herbal Face Wash"),
        ("VERDA006", "Natural Lip Balm"),
        ("VERDA007", "Compostable Trash Bags"),
        ("VERDA008", "Organic Body Lotion"),
        ("VERDA009", "Bamboo Cutlery Set"),
        ("VERDA010", "Reusable Grocery Bag"),
    ]
    return render_template('print_qr.html', products=products)

@app.route('/pdf-report')
def pdf_report():
    if not session.get('logged_in'):
        return redirect('/login')
    conn = get_db()
    scans = conn.execute(
        "SELECT product_id, COUNT(*) as count FROM scans GROUP BY product_id"
    ).fetchall()
    products = conn.execute("SELECT * FROM products").fetchall()
    conn.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Verda Product Verification Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Scan Activity Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(46, 125, 50)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(60, 8, "Product ID", border=1, fill=True)
    pdf.cell(40, 8, "Total Scans", border=1, fill=True)
    pdf.cell(60, 8, "Status", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    for scan in scans:
        count = scan['count']
        status = "Authentic" if count < 5 else "Suspicious" if count < 15 else "Fake"
        pdf.cell(60, 8, scan['product_id'], border=1)
        pdf.cell(40, 8, str(count), border=1)
        pdf.cell(60, 8, status, border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Registered Products", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(46, 125, 50)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(40, 8, "Product ID", border=1, fill=True)
    pdf.cell(80, 8, "Name", border=1, fill=True)
    pdf.cell(50, 8, "Category", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    for product in products:
        pdf.cell(40, 8, product['product_id'], border=1)
        pdf.cell(80, 8, product['name'], border=1)
        pdf.cell(50, 8, product['category'], border=1, new_x="LMARGIN", new_y="NEXT")

    response = make_response(pdf.output())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=verda_report.pdf'
    return response

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)