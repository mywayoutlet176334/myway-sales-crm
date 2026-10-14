import json
import tempfile
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from app import create_app
from assistant import analyze,draft,TZ,CATEGORIES

AT=datetime(2026,10,12,17,0,tzinfo=TZ)
def message(id,text,direction='inbound',hours=0,attachment=None):
    m=dict(id=id,text=text,direction=direction,timestamp=(AT+timedelta(hours=hours)).isoformat())
    if attachment: m['attachment']=attachment
    return m

class AnalysisTests(unittest.TestCase):
    def test_all_categories(self):
        for category,text in [('Karaoke','karaoke'),('Indoor LED','indoor LED'),('Outdoor LED','outdoor LED'),('LED Poster','LED poster'),('Pro Sound','pro sound'),('Home Theater','home theater'),('Smart Home','smart home'),('Technical Support','karaoke not working'),('Other','hello')]:
            self.assertEqual(analyze([message('1',text)],AT)['category'],category)
    def test_prices_are_not_automatically_quotations(self):
        for text,direction in [('My budget is RM 5000','inbound'),('How much? RM 5000?','inbound'),('Prices starting from RM 1000','outbound'),('Our offer is roughly RM 2000','outbound')]:
            result=analyze([message('1',text,direction)],AT)
            self.assertFalse(result['quoted']); self.assertEqual(result['evidence'][0]['kind'],'General price discussion')
        result=analyze([message('1','Our offer: RM 12000, package includes installation','outbound',-72)],AT)
        self.assertTrue(result['quoted']); self.assertEqual(result['state'],'Needs follow-up')
    def test_pdf_evidence_and_direction(self):
        brochure={'mime':'application/pdf','filename':'quotation.pdf','extracted_text':'catalogue RM 1000'}
        result=analyze([message('1','Brochure','outbound',attachment=brochure)],AT)
        self.assertFalse(result['quoted']); self.assertEqual(result['evidence'][0]['kind'],'PDF needs review')
        formal={'mime':'application/pdf','filename':'QT10.pdf','extracted_text':'Quotation QT10 RM 12000'}
        self.assertTrue(analyze([message('1','Attached','outbound',attachment=formal)],AT)['quoted'])
        self.assertFalse(analyze([message('1','Competitor quote','inbound',attachment=formal)],AT)['quoted'])
    def test_replies_waiting_and_future_cutoff(self):
        result=analyze([message('1','Our offer RM 5000','outbound',-72),message('2','Thanks, urgent this week','inbound',-1)],AT)
        self.assertEqual(result['state'],'Customer replied'); self.assertTrue(result['urgent']); self.assertFalse(result['needs_followup'])
        self.assertEqual(analyze([message('1','请报价','inbound',-1)],AT)['state'],'Waiting for quotation')
        self.assertFalse(analyze([message('1','Our offer RM 5000','outbound',1)],AT)['quoted'])
    def test_multilingual_drafts(self):
        for language in ['en','zh','ms']:
            text=draft('Aina','Smart Home','Waiting for quotation',language)
            self.assertIn('Aina',text); self.assertIn('MYWAY',text); self.assertLess(len(text),300)
        self.assertIn('sebut harga',draft('Aina','Smart Home','Waiting for quotation','ms'))

class AssistantIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.app=create_app(self.temp.name); self.app.config['TESTING']=True
        with self.app.db() as c:
            c.execute('INSERT INTO users(username,password) VALUES(?,?)',('owner',generate_password_hash('a-long-password')))
            c.execute("INSERT INTO customers VALUES(1,'Existing','60123456789','Karaoke','KL','Keep me','Customer')")
            c.execute("INSERT INTO quotations VALUES(1,1,'EXISTING',50000,'2026-10-01','Sent',NULL,NULL)")
            c.execute("INSERT INTO followups VALUES(1,1,2,'2026-10-03','Pending')")
        self.client=self.app.test_client(); self.client.get('/login')
        self.post('/login',username='owner',password='a-long-password')
    def tearDown(self): self.temp.cleanup()
    def post(self,path,**data):
        with self.client.session_transaction() as s: data['csrf']=s['csrf']
        return self.client.post(path,data=data,follow_redirects=True)
    def load(self):
        with patch('assistant.now',return_value=AT.replace(hour=12)): return self.post('/assistant',action='samples')
    def test_sample_import_idempotent_preserves_originals(self):
        self.load(); self.load()
        with self.app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM assistant_chats').fetchone()[0],9)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM assistant_messages').fetchone()[0],14)
            self.assertEqual(c.execute('SELECT name FROM customers').fetchone()[0],'Existing')
            self.assertEqual(c.execute('SELECT number FROM quotations').fetchone()[0],'EXISTING')
            self.assertEqual(c.execute('SELECT status FROM followups').fetchone()[0],'Pending')
        for path in ['/assistant','/assistant/queue','/assistant/summary']:
            self.assertEqual(self.client.get(path).status_code,200)
    def test_approval_edit_reject_and_duplicate(self):
        self.load()
        for _ in range(2): self.post('/assistant',action='draft',chat_id='sample-indoor',language='zh')
        with self.app.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM assistant_queue').fetchone()[0],1)
        self.post('/assistant/queue',id='1',action='approve',text='Reviewed text')
        with self.app.db() as c:
            row=c.execute('SELECT * FROM assistant_queue').fetchone()
            self.assertEqual(row['status'],'Approved'); self.assertEqual(row['text'],'Reviewed text'); self.assertEqual(row['reviewer'],1)
        self.assertEqual(self.post('/assistant/queue',id='1',action='approve',text='Repeat').status_code,409)
        self.post('/assistant',action='draft',chat_id='sample-indoor',language='en')
        self.post('/assistant/queue',id='2',action='reject',text='No thanks')
        self.assertIn(b'Rejected',self.client.get('/assistant/queue').data)
    def test_auth_csrf_and_no_send_endpoint(self):
        anon=self.app.test_client()
        for path in ['/assistant','/assistant/queue','/assistant/summary']: self.assertEqual(anon.get(path).status_code,302)
        self.assertEqual(self.client.post('/assistant',data={'action':'samples'}).status_code,400)
        self.assertEqual(self.post('/assistant/send').status_code,404)
    def test_review_overrides(self):
        self.load()
        self.post('/assistant',action='review',chat_id='sample-other',category='Karaoke',state='Waiting for quotation')
        self.post('/assistant',action='draft',chat_id='sample-other',language='en')
        with self.app.db() as c: self.assertIn('Karaoke',c.execute('SELECT text FROM assistant_queue').fetchone()[0])
    def test_pasted_chat_analysis_and_manual_draft(self):
        response=self.post('/assistant',action='paste',name='Paste Test',language='zh',chat_date='2026-01-01T10:00',conversation='客户: 我想买 karaoke，请报价。\n我: Our offer is RM 5000, package includes installation.\n客户: Thanks')
        self.assertIn(b'Paste Test',response.data)
        with self.app.db() as c:
            chat=c.execute("SELECT * FROM assistant_chats WHERE id LIKE 'paste-%'").fetchone()
            messages=[json.loads(r[0]) for r in c.execute('SELECT payload FROM assistant_messages WHERE chat_id=?',(chat['id'],))]
            self.assertEqual([m['direction'] for m in messages],['inbound','outbound','inbound'])
            self.assertEqual(analyze(messages)['state'],'Customer replied')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],1)
        self.post('/assistant',action='draft',chat_id=chat['id'],language='zh')
        self.post('/assistant/queue',id='1',action='approve',text='Reviewed manual message')
        self.assertIn(b'Reviewed manual message',self.client.get('/assistant/queue').data)
    def test_paste_validation_does_not_save_partial_chat(self):
        for content,stamp in [('unlabelled text','2026-01-01T10:00'),('客户: hi','2099-01-01T10:00'),('客户: hi','invalid'),('x'*30001,'2026-01-01T10:00')]:
            self.post('/assistant',action='paste',name='Test',language='en',chat_date=stamp,conversation=content)
        with self.app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM assistant_chats').fetchone()[0],0)
    def test_paste_text_is_escaped(self):
        response=self.post('/assistant',action='paste',name='<script>alert(1)</script>',language='en',chat_date='2026-01-01T10:00',conversation='客户: <script>alert(2)</script>')
        self.assertNotIn(b'<script>',response.data)
        self.assertIn(b'&lt;script&gt;',response.data)

    def test_no_empty_summary_before_loading_chats(self):
        with patch('assistant.now',return_value=AT): self.assertFalse(self.app.assistant_summary())

    def test_summary_5pm_deduplication_and_persistence(self):
        self.load()
        with patch('assistant.now',return_value=AT.replace(hour=16,minute=59)): self.assertFalse(self.app.assistant_summary())
        with patch('assistant.now',return_value=AT):
            self.assertTrue(self.app.assistant_summary()); self.assertFalse(self.app.assistant_summary())
        second=create_app(self.temp.name)
        with second.db() as c:
            row=c.execute('SELECT * FROM assistant_summaries').fetchone()
            self.assertIn('17:00:00+08:00',row['cutoff'])
            data=json.loads(row['payload']); self.assertEqual(data['counts']['followups'],1)
            self.assertEqual(data['counts']['quotations'],0) # examples were sent on earlier days
            self.assertIn('Demo • Amir',data['waiting'])


class SendingPolicyTests(unittest.TestCase):
    def test_gate_never_enables_sending_by_approval_alone(self):
        from sending_policy import sending_blockers
        base=dict(approved=True,live_enabled=False,connection_approved=False,opt_in=True,opted_out=False,last_customer_message=AT-timedelta(hours=1),at=AT)
        self.assertEqual(len(sending_blockers(**base)),2)
        base.update(live_enabled=True,connection_approved=True)
        self.assertEqual(sending_blockers(**base),[])
        base['last_customer_message']=AT-timedelta(hours=24)
        self.assertIn('Outside customer-service window: approved template required',sending_blockers(**base))
        base.update(template_approved=True,opted_out=True,closed_deal=True)
        blockers=sending_blockers(**base)
        self.assertIn('Consent missing or customer opted out',blockers)
        self.assertIn('Won/Lost deal: sales follow-ups stopped',blockers)

if __name__=='__main__': unittest.main()
