import os, re, secrets, sqlite3, time, uuid
from datetime import datetime, timedelta, date
from decimal import Decimal, InvalidOperation
from functools import wraps
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import click
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash

PRODUCTS = ['Indoor Fixed LED','Outdoor Fixed LED','Standard LED Poster','Tri-Fold LED Poster','Karaoke','Pro Sound','Smart Home','Home Theater','Other']
STATUSES = ['Draft','Sent','Won','Lost']
CUSTOMER_STATUSES = ['New','Contacted','Quoted','Customer','Inactive']

def today():
    return datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).date()

def create_app(data_dir=None):
    app = Flask(__name__)
    root = Path(data_dir or os.environ.get('CRM_DATA_DIR', 'instance')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root/'uploads').mkdir(exist_ok=True)
    keyfile = root/'session.key'
    if not keyfile.exists():
        try:
            with keyfile.open('x') as f: f.write(secrets.token_hex(32))
            keyfile.chmod(0o600)
        except FileExistsError: pass
    app.config.update(SECRET_KEY=keyfile.read_text(), MAX_CONTENT_LENGTH=10*1024*1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('CRM_HTTPS') == '1', PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    @contextmanager
    def db():
        conn = sqlite3.connect(root/'crm.sqlite3', timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    app.db = db
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, product TEXT NOT NULL, location TEXT NOT NULL, notes TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quotations(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), number TEXT UNIQUE NOT NULL, cents INTEGER NOT NULL, sent_date TEXT, status TEXT NOT NULL, pdf TEXT, pdf_name TEXT);
        CREATE TABLE IF NOT EXISTS followups(id INTEGER PRIMARY KEY, quotation_id INTEGER NOT NULL REFERENCES quotations(id), day INTEGER NOT NULL, due TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending');
        CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, quotation_id INTEGER NOT NULL REFERENCES quotations(id), created TEXT NOT NULL, note TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts(username TEXT PRIMARY KEY, count INTEGER NOT NULL, until REAL NOT NULL);
        ''')
    def login_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user'): return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return wrapped
    @app.before_request
    def protect():
        if 'csrf' not in session: session['csrf'] = secrets.token_hex(32)
        if request.method == 'POST' and not secrets.compare_digest(session['csrf'], request.form.get('csrf','')): abort(400)
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers['Cache-Control']='no-store'
        return response
    @app.context_processor
    def context():
        return dict(products=PRODUCTS, statuses=STATUSES, customer_statuses=CUSTOMER_STATUSES, today=str(today()))
    app.jinja_env.filters['rm'] = lambda cents: f'RM {cents/100:,.2f}'
    def parsed_date(value):
        return date.fromisoformat(value).isoformat()
    def phone(value):
        digits=re.sub(r'[\s()+-]', '', value)
        if digits.startswith('00'): digits=digits[2:]
        if digits.startswith('0'): digits='60'+digits[1:]
        if not digits.isdigit() or not 8 <= len(digits) <= 15: raise ValueError('Enter a valid WhatsApp number with country code.')
        return digits
    def schedule(c, qid, sent):
        c.execute('DELETE FROM followups WHERE quotation_id=?', (qid,))
        for day in (2,5,10): c.execute('INSERT INTO followups(quotation_id,day,due) VALUES(?,?,?)',(qid,day,str(date.fromisoformat(sent)+timedelta(days=day))))
    def log(c, qid, note):
        c.execute('INSERT INTO activity(quotation_id,created,note) VALUES(?,?,?)',(qid,datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).isoformat(timespec='minutes'),note))
    @app.route('/login', methods=['GET','POST'])
    def login():
        if request.method=='POST':
            username=request.form.get('username','').strip().lower()
            with db() as c:
                attempt=c.execute('SELECT * FROM login_attempts WHERE username=?',(username,)).fetchone()
                if attempt and attempt['count']>=5 and attempt['until']>time.time():
                    flash('Too many attempts. Try again in 15 minutes.'); return render_template('login.html'),429
                user=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
                if user and check_password_hash(user['password'],request.form.get('password','')):
                    c.execute('DELETE FROM login_attempts WHERE username=?',(username,))
                    session.clear(); session['user']=user['id']; session['csrf']=secrets.token_hex(32); session.permanent=True
                    return redirect(url_for('dashboard'))
                count=attempt['count']+1 if attempt and attempt['until']>time.time() else 1
                c.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(username,count,time.time()+900))
            flash('Incorrect username or password.')
        return render_template('login.html')
    @app.post('/logout')
    def logout():
        session.clear(); return redirect(url_for('login'))
    def followup_rows(c):
        rows=c.execute('''SELECT f.*,q.number,q.cents,c.name,c.phone FROM followups f JOIN quotations q ON q.id=f.quotation_id JOIN customers c ON c.id=q.customer_id WHERE f.status='Pending' AND q.status='Sent' ORDER BY f.due,f.id''').fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            item['whatsapp']='https://wa.me/'+row['phone']+'?'+urlencode({'text':f"Hi {row['name']}, following up on MYWAY quotation {row['number']}. Do you have any questions? Happy to help."})
            result.append(item)
        return result
    @app.get('/')
    @login_required
    def dashboard():
        with db() as c:
            rows=followup_rows(c)
            summary=c.execute("SELECT COUNT(*) count, COALESCE(SUM(cents),0) value FROM quotations WHERE status='Sent'").fetchone()
            won=c.execute("SELECT COUNT(*) FROM quotations WHERE status='Won'").fetchone()[0]
        return render_template('dashboard.html', rows=[r for r in rows if r['due']<=str(today())], due=sum(r['due']==str(today()) for r in rows), overdue=sum(r['due']<str(today()) for r in rows),summary=summary,won=won)
    @app.route('/customers',methods=['GET','POST'])
    @login_required
    def customers():
        if request.method=='POST':
            try:
                f=request.form; name=f.get('name','').strip()
                if not name or len(name)>200: raise ValueError('Customer name is required (maximum 200 characters).')
                if f.get('product') not in PRODUCTS or f.get('status') not in CUSTOMER_STATUSES: raise ValueError('Choose a valid product and status.')
                values=(name,phone(f.get('phone','')),f['product'],f.get('location','').strip(),f.get('notes','').strip(),f['status'])
                with db() as c:
                    if f.get('id'):
                        if not c.execute('SELECT id FROM customers WHERE id=?',(f['id'],)).fetchone(): abort(404)
                        c.execute('UPDATE customers SET name=?,phone=?,product=?,location=?,notes=?,status=? WHERE id=?',values+(f['id'],))
                    else: c.execute('INSERT INTO customers(name,phone,product,location,notes,status) VALUES(?,?,?,?,?,?)',values)
                flash('Customer saved.'); return redirect(url_for('customers'))
            except ValueError as e: flash(str(e))
        with db() as c:
            rows=c.execute('SELECT * FROM customers ORDER BY name').fetchall()
            edit=c.execute('SELECT * FROM customers WHERE id=?',(request.args.get('edit'),)).fetchone()
        return render_template('customers.html',rows=rows,edit=edit)
    @app.route('/quotations', methods=['GET','POST'])
    @login_required
    def quotations():
        if request.method=='POST':
            saved=None
            try:
                f=request.form; number=f.get('number','').strip(); status=f.get('status')
                if not number or len(number)>100 or status not in STATUSES: raise ValueError('Enter a quotation number and valid status.')
                amount=Decimal(f.get('amount',''))
                if not amount.is_finite() or amount<0 or amount>Decimal('999999999.99') or amount!=amount.quantize(Decimal('.01')): raise ValueError('Enter a valid amount with at most two decimal places.')
                sent=parsed_date(f['sent_date']) if f.get('sent_date') else None
                if status=='Sent' and not sent: raise ValueError('Date sent is required for a Sent quotation.')
                file=request.files.get('pdf'); filename=None
                if file and file.filename:
                    data=file.read()
                    if not file.filename.lower().endswith('.pdf') or not data.startswith(b'%PDF-'): raise ValueError('Upload a PDF file only (maximum 10 MB).')
                    saved=uuid.uuid4().hex+'.pdf'; filename=Path(file.filename).name
                    (root/'uploads'/saved).write_bytes(data)
                with db() as c:
                    if not c.execute('SELECT id FROM customers WHERE id=?',(f.get('customer_id'),)).fetchone(): raise ValueError('Choose an existing customer first.')
                    old=c.execute('SELECT * FROM quotations WHERE id=?',(f.get('id'),)).fetchone() if f.get('id') else None
                    if f.get('id') and not old: abort(404)
                    if old:
                        qid=old['id']
                        if old['sent_date'] and sent!=old['sent_date'] and status=='Sent': raise ValueError('Keep the original sent date. Reschedule individual follow-ups instead.')
                        c.execute('UPDATE quotations SET customer_id=?,number=?,cents=?,sent_date=?,status=?,pdf=?,pdf_name=? WHERE id=?',(f['customer_id'],number,int(amount*100),sent,status,saved or old['pdf'],filename or old['pdf_name'],qid))
                    else:
                        qid=c.execute('INSERT INTO quotations(customer_id,number,cents,sent_date,status,pdf,pdf_name) VALUES(?,?,?,?,?,?,?)',(f['customer_id'],number,int(amount*100),sent,status,saved,filename)).lastrowid
                    if status=='Sent' and (not old or old['status']!='Sent'): schedule(c,qid,sent)
                    if status!='Sent': c.execute("UPDATE followups SET status='Stopped' WHERE quotation_id=? AND status='Pending'",(qid,))
                    log(c,qid,'Quotation '+status)
                flash('Quotation saved.'); return redirect(url_for('quotations'))
            except (ValueError,InvalidOperation,sqlite3.IntegrityError) as e:
                if saved: (root/'uploads'/saved).unlink(missing_ok=True)
                flash('Quotation number must be unique.' if isinstance(e,sqlite3.IntegrityError) else str(e) or 'Enter a valid amount.')
        with db() as c:
            rows=c.execute('SELECT q.*,c.name FROM quotations q JOIN customers c ON c.id=q.customer_id ORDER BY q.id DESC').fetchall()
            people=c.execute('SELECT * FROM customers ORDER BY name').fetchall()
            edit=c.execute('SELECT * FROM quotations WHERE id=?',(request.args.get('edit'),)).fetchone()
        return render_template('quotations.html',rows=rows,people=people,edit=edit)
    @app.get('/quotations/<int:qid>/pdf')
    @login_required
    def pdf(qid):
        with db() as c: q=c.execute('SELECT * FROM quotations WHERE id=?',(qid,)).fetchone()
        if not q or not q['pdf']: abort(404)
        return send_from_directory(root/'uploads',q['pdf'],as_attachment=True,download_name=q['pdf_name'],mimetype='application/pdf')
    @app.route('/follow-ups',methods=['GET','POST'])
    @login_required
    def followups():
        if request.method=='POST':
            try:
                f=request.form
                with db() as c:
                    row=c.execute("SELECT f.* FROM followups f JOIN quotations q ON q.id=f.quotation_id WHERE f.id=? AND f.status='Pending' AND q.status='Sent'",(f.get('id'),)).fetchone()
                    if not row: raise ValueError('This reminder is no longer active.')
                    action=f.get('action'); note=f.get('note','').strip()
                    if action=='done': c.execute("UPDATE followups SET status='Done' WHERE id=?",(row['id'],))
                    elif action=='stop': c.execute("UPDATE followups SET status='Stopped' WHERE quotation_id=? AND status='Pending'",(row['quotation_id'],))
                    elif action in ('reschedule','snooze','reply'):
                        if action=='reply' and not note: raise ValueError('Enter the customer reply.')
                        due=str(max(today(),date.fromisoformat(row['due']))+timedelta(days=1)) if action=='snooze' else parsed_date(f.get('due',''))
                        c.execute('UPDATE followups SET due=? WHERE id=?',(due,row['id']))
                    else: raise ValueError('Choose an action.')
                    log(c,row['quotation_id'],f'Day {row["day"]}: {action}'+(f' — {note}' if note else ''))
                flash('Follow-up updated.'); return redirect(url_for('followups'))
            except ValueError as e: flash(str(e))
        with db() as c:
            rows=followup_rows(c)
            history=c.execute('SELECT a.*,q.number FROM activity a JOIN quotations q ON q.id=a.quotation_id ORDER BY a.id DESC LIMIT 100').fetchall()
        return render_template('followups.html',rows=rows,history=history)
    @app.errorhandler(413)
    def too_large(e): return 'The PDF is too large. Maximum upload size is 10 MB.',413
    @app.cli.command('create-user')
    @click.argument('username')
    @click.password_option(confirmation_prompt=True)
    def create_user(username,password):
        if len(password)<12: raise click.ClickException('Use at least 12 characters.')
        with db() as c:
            c.execute('INSERT INTO users(username,password) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET password=excluded.password',(username.strip().lower(),generate_password_hash(password)))
        click.echo('Login created or password updated.')
    @app.cli.command('seed-demo')
    def seed_demo():
        with db() as c:
            if c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]: raise click.ClickException('Demo data only loads into an empty database.')
            for i,(name,product,days,status) in enumerate([('Demo • Cahaya Café','Indoor Fixed LED',2,'Sent'),('Demo • Maju Events','Pro Sound',6,'Sent'),('Demo • Home Studio','Karaoke',0,'Draft'),('Demo • Pavilion Shop','Standard LED Poster',12,'Won')],1):
                cid=c.execute('INSERT INTO customers(name,phone,product,location,notes,status) VALUES(?,?,?,?,?,?)',(name,'60100000000',product,'Kuala Lumpur','Fictional sample. Replace phone before using WhatsApp.','Quoted')).lastrowid
                sent=str(today()-timedelta(days=days)) if status!='Draft' else None
                qid=c.execute('INSERT INTO quotations(customer_id,number,cents,sent_date,status) VALUES(?,?,?,?,?)',(cid,f'DEMO-{i:03}',i*1250000,sent,status)).lastrowid
                if status=='Sent': schedule(c,qid,sent)
        click.echo('Fictional demo customers and quotations added. No login or PDF was created.')
    from assistant import install_assistant
    install_assistant(app, db, login_required)
    return app

app = create_app()
if __name__=='__main__': app.run(host='127.0.0.1',port=5000)
