import io
import tempfile
import unittest
from datetime import timedelta
from app import create_app, today
from werkzeug.security import generate_password_hash

class CRMTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(self.temp.name)
        self.app.config['TESTING']=True
        self.client=self.app.test_client()
        with self.app.db() as c:
            c.execute('INSERT INTO users(username,password) VALUES(?,?)',('owner',generate_password_hash('a-long-test-password')))
        self.client.get('/login')
        self.post('/login',username='owner',password='a-long-test-password')
    def tearDown(self): self.temp.cleanup()
    def post(self,path,**data):
        with self.client.session_transaction() as s: data['csrf']=s['csrf']
        return self.client.post(path,data=data,follow_redirects=True)
    def customer(self):
        return self.post('/customers',name='Test Customer',phone='012-3456789',product='Karaoke',location='KL',notes='Interested',status='Quoted')
    def quote(self,**overrides):
        data=dict(customer_id='1',number='Q-001',amount='1200.50',sent_date=str(today()),status='Sent')
        data.update(overrides)
        return self.post('/quotations',**data)
    def test_auth_csrf_and_lockout(self):
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/').status_code,302)
        self.assertEqual(anonymous.get('/quotations/1/pdf').status_code,302)
        self.assertEqual(self.client.post('/customers',data={'name':'Bad'}).status_code,400)
        self.post('/logout'); self.client.get('/login')
        for _ in range(5): self.post('/login',username='owner',password='wrong')
        self.assertEqual(self.post('/login',username='owner',password='a-long-test-password').status_code,429)
    def test_pages_and_persistence(self):
        self.customer(); self.quote()
        for page in ['/','/customers','/quotations','/follow-ups','/customers?edit=1','/quotations?edit=1']:
            self.assertEqual(self.client.get(page).status_code,200)
        second=create_app(self.temp.name)
        with second.db() as c:
            self.assertEqual(c.execute('SELECT phone FROM customers').fetchone()[0],'60123456789')
            self.assertEqual(c.execute('SELECT cents FROM quotations').fetchone()[0],120050)
    def test_schedule_multiple_quotes_and_won(self):
        self.customer(); self.quote(); self.quote(number='Q-002')
        with self.app.db() as c:
            rows=c.execute('SELECT day,due FROM followups WHERE quotation_id=1 ORDER BY day').fetchall()
            self.assertEqual([(r['day'],r['due']) for r in rows],[(n,str(today()+timedelta(days=n))) for n in (2,5,10)])
        self.quote(id='1',status='Won')
        with self.app.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM followups WHERE quotation_id=1 AND status='Pending'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM followups WHERE quotation_id=2 AND status='Pending'").fetchone()[0],3)
        self.assertIn(b'RM 1,200.50',self.client.get('/').data)
    def test_reminder_actions(self):
        self.customer(); self.quote()
        self.post('/follow-ups',id='1',action='snooze')
        with self.app.db() as c: self.assertEqual(c.execute('SELECT due FROM followups WHERE id=1').fetchone()[0],str(today()+timedelta(days=3)))
        future=str(today()+timedelta(days=8))
        self.post('/follow-ups',id='1',action='reply',due=future,note='Please call next week')
        self.assertIn(b'Please call next week',self.client.get('/follow-ups').data)
        self.post('/follow-ups',id='1',action='done')
        self.post('/follow-ups',id='2',action='reschedule',due=str(today()))
        self.assertIn(b'Today',self.client.get('/follow-ups').data)
        self.post('/follow-ups',id='2',action='stop')
        with self.app.db() as c: self.assertEqual(c.execute("SELECT COUNT(*) FROM followups WHERE status='Pending'").fetchone()[0],0)
    def test_pdf_download_and_invalid_upload(self):
        self.customer()
        data=b'%PDF-1.4\nTest quotation\n%%EOF'
        self.quote(pdf=(io.BytesIO(data),'quotation.pdf'))
        response=self.client.get('/quotations/1/pdf')
        self.assertEqual(response.data,data)
        self.assertIn('attachment',response.headers['Content-Disposition'])
        response.close()
        self.assertIn(b'Upload a PDF file only',self.quote(number='Q-002',pdf=(io.BytesIO(b'not pdf'),'bad.pdf')).data)
    def test_validation_lost_and_idempotent_save(self):
        self.customer(); self.quote()
        self.quote(id='1')
        with self.app.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM followups').fetchone()[0],3)
        self.assertIn(b'valid amount',self.quote(number='Q-002',amount='1.001').data)
        self.assertIn(b'unique',self.quote().data)
        self.assertIn(b'Date sent is required',self.quote(number='Q-003',sent_date='').data)
        self.quote(id='1',status='Lost')
        with self.app.db() as c: self.assertEqual(c.execute("SELECT COUNT(*) FROM followups WHERE status='Pending'").fetchone()[0],0)
    def test_overdue_dashboard_and_whatsapp(self):
        self.customer(); self.quote(sent_date=str(today()-timedelta(days=5)))
        page=self.client.get('/').data
        self.assertIn(b'Overdue',page); self.assertIn(b'Today',page)
        self.assertIn(b'https://wa.me/60123456789?',page)
        self.assertIn(b'press Send manually',page)

if __name__=='__main__': unittest.main()
