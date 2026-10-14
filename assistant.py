"""Offline assistant extension. No network client and no live sending capability."""
import json
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort
import click

TZ=ZoneInfo('Asia/Kuala_Lumpur')
CATEGORIES=['Karaoke','Indoor LED','Outdoor LED','LED Poster','Pro Sound','Home Theater','Smart Home','Technical Support','Other']
KEYWORDS={
 'Technical Support':['repair','not working','故障','维修','rosak','technical support'],
 'LED Poster':['led poster','poster led','tri-fold','海报屏'],
 'Outdoor LED':['outdoor led','outdoor screen','户外','led luar'],
 'Indoor LED':['indoor led','indoor screen','室内','led dalaman'],
 'Karaoke':['karaoke','卡拉','ktv'], 'Pro Sound':['pro sound','pa system','音响','speaker system'],
 'Home Theater':['home theater','home theatre','家庭影院'], 'Smart Home':['smart home','智能家居','rumah pintar']}
STATES=['Waiting for quotation','Quotation received','Customer replied','Needs follow-up','Unanswered enquiry']

def now(): return datetime.now(TZ)

def parse_time(value):
    value=datetime.fromisoformat(value)
    if value.tzinfo is None: raise ValueError('Chat timestamps must include a timezone.')
    return value.astimezone(TZ)

def analyze(messages, at=None):
    """Conservative rules with reviewable evidence; not a trained AI or PDF reader."""
    at=at or now()
    ordered=sorted(messages,key=lambda m:parse_time(m['timestamp']))
    visible=[m for m in ordered if parse_time(m['timestamp'])<=at]
    texts=' '.join(m.get('text','') for m in visible).lower()
    matches=[cat for cat,terms in KEYWORDS.items() if any(t in texts for t in terms)]
    category=matches[0] if matches else 'Other'
    evidence=[]; quoted=False; inbound=None; outbound=None; latest_quote=None
    waiting=False; urgent=False
    for m in visible:
        text=m.get('text',''); low=text.lower(); stamp=parse_time(m['timestamp'])
        kind=None
        if m['direction']=='inbound':
            inbound=stamp
            if any(x in low for x in ['send quotation','send a quotation','waiting for quotation','quotation please','报价','sebut harga']): waiting=True
            urgent=urgent or any(x in low for x in ['urgent','today','this week','紧急','segera','minggu ini'])
        else:
            outbound=stamp
        attachment=m.get('attachment',{})
        if attachment.get('mime')=='application/pdf':
            # Filename alone never proves a formal quotation. Text here is supplied sample extraction.
            extracted=attachment.get('extracted_text','').lower()
            formal=bool(re.search(r'(quotation|sebut harga|报价)',extracted) and re.search(r'(rm|myr)\s*[\d,]+',extracted) and re.search(r'(quote|quotation|qt)[\s:#-]*[a-z]*\d',extracted))
            kind='Formal quotation PDF candidate' if formal else 'PDF needs review'
            if formal and m['direction']=='outbound': quoted=True; waiting=False; latest_quote=stamp
        elif re.search(r'(rm|myr)\s*[\d,]+(?:\.\d{1,2})?',low):
            concrete=any(x in low for x in ['i offer','we offer','our offer','quotation','installed price','package includes','报价','pakej termasuk','tawaran kami'])
            uncertain=any(x in low for x in ['from rm','starting','roughly','around','budget','how much','estimate','anggaran','大概','起价'])
            kind='Informal offer candidate' if m['direction']=='outbound' and concrete and not uncertain else 'General price discussion'
            if kind=='Informal offer candidate': quoted=True; waiting=False; latest_quote=stamp
        if kind: evidence.append({'id':m['id'],'kind':kind,'text':text,'filename':attachment.get('filename','')})
    unanswered=bool(inbound and (not outbound or inbound>outbound))
    replied=bool(inbound and latest_quote and inbound>latest_quote)
    needs=bool(quoted and not unanswered and latest_quote and at>=latest_quote+timedelta(days=2))
    state='Waiting for quotation' if waiting else 'Customer replied' if replied else 'Unanswered enquiry' if unanswered else 'Needs follow-up' if needs else 'Quotation received' if quoted else 'Unanswered enquiry'
    return dict(category=category,matches=matches,state=state,evidence=evidence,quoted=quoted,
                unanswered=unanswered,replied=replied,needs_followup=needs,urgent=urgent,
                last_inbound=inbound.isoformat() if inbound else None,review_required=True)

def draft(name, category, state, language):
    topic=category if category!='Other' else 'your project'
    if language=='zh':
        topic={'Karaoke':'卡拉OK','Indoor LED':'室内LED屏','Outdoor LED':'户外LED屏','LED Poster':'LED海报屏','Pro Sound':'专业音响','Home Theater':'家庭影院','Smart Home':'智能家居','Technical Support':'技术支持','Other':'您的项目'}[category]
        action='想确认一下您的报价需求' if state=='Waiting for quotation' else '想跟进一下您的报价' if state in ['Quotation received','Needs follow-up'] else '谢谢您的咨询，想了解一下您的需求'
        return f'您好 {name}，我是MYWAY。关于{topic}，{action}。请问还有什么需要我们协助？'
    if language=='ms':
        topic={'Karaoke':'karaoke','Indoor LED':'LED dalaman','Outdoor LED':'LED luaran','LED Poster':'poster LED','Pro Sound':'sistem bunyi profesional','Home Theater':'teater rumah','Smart Home':'rumah pintar','Technical Support':'sokongan teknikal','Other':'projek anda'}[category]
        action='Boleh kami sahkan keperluan sebut harga anda?' if state=='Waiting for quotation' else 'Ada soalan tentang tawaran kami?' if state in ['Quotation received','Needs follow-up'] else 'Bagaimana kami boleh membantu?'
        return f'Hai {name}, saya dari MYWAY. Saya ingin membuat susulan tentang {topic}. {action}'
    action='Could we confirm what you need for your quotation?' if state=='Waiting for quotation' else 'Do you have any questions about our offer?' if state in ['Quotation received','Needs follow-up'] else 'How can we help with your enquiry?'
    return f'Hi {name}, this is MYWAY. Following up on {topic}. {action}'

def parse_pasted_chat(text, end_time):
    """Require explicit speakers; never guess direction from WhatsApp display names."""
    if not text.strip() or len(text)>30000:
        raise ValueError('请粘贴聊天内容，最多 30,000 个字符。')
    messages=[]
    for line in text.splitlines():
        if not line.strip(): continue
        match=re.match(r'^\s*(客户|Customer|MYWAY|我|Me)\s*[:：]\s*(.*)$',line,re.I)
        if match:
            body=match.group(2).strip()
            if not body: raise ValueError('每条消息必须有内容。')
            direction='inbound' if match.group(1).lower() in ['客户','customer'] else 'outbound'
            messages.append(dict(id=uuid.uuid4().hex,text=body,direction=direction))
        elif messages:
            messages[-1]['text']+='\n'+line
        else:
            raise ValueError('请在消息前加「客户:」或「我:」，让系统分清谁说的话。')
    if not messages: raise ValueError('没有可分析的消息。')
    for i,m in enumerate(messages):
        m['timestamp']=(end_time-timedelta(seconds=len(messages)-1-i)).isoformat()
    return messages

def install_assistant(app,db,login_required):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS assistant_chats(id TEXT PRIMARY KEY,name TEXT NOT NULL,language TEXT NOT NULL,category_override TEXT, state_override TEXT);
        CREATE TABLE IF NOT EXISTS assistant_messages(id TEXT PRIMARY KEY,chat_id TEXT NOT NULL REFERENCES assistant_chats(id),timestamp TEXT NOT NULL,direction TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assistant_queue(id INTEGER PRIMARY KEY,chat_id TEXT NOT NULL REFERENCES assistant_chats(id),language TEXT NOT NULL,text TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Pending',created TEXT NOT NULL,reviewer INTEGER,reviewed TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS assistant_one_pending ON assistant_queue(chat_id) WHERE status='Pending';
        CREATE TABLE IF NOT EXISTS assistant_imports(chat_id TEXT PRIMARY KEY REFERENCES assistant_chats(id),created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assistant_summaries(day TEXT PRIMARY KEY,cutoff TEXT NOT NULL,payload TEXT NOT NULL);
        ''')
    def chats(c,at=None):
        result=[]
        for row in c.execute('SELECT * FROM assistant_chats ORDER BY name').fetchall():
            messages=[json.loads(m['payload']) for m in c.execute('SELECT payload FROM assistant_messages WHERE chat_id=? ORDER BY timestamp,id',(row['id'],))]
            analysis=analyze(messages,at)
            effective=dict(analysis)
            if row['category_override']: effective['category']=row['category_override']
            if row['state_override']: effective['state']=row['state_override']
            result.append(dict(row)|dict(analysis=analysis,effective=effective,messages=messages))
        return result
    def import_samples(c):
        from pathlib import Path
        data=json.loads((Path(__file__).parent/'samples/chats.json').read_text())
        anchor=now().replace(hour=12,minute=0,second=0,microsecond=0)
        for chat in data:
            c.execute('INSERT OR IGNORE INTO assistant_chats(id,name,language) VALUES(?,?,?)',(chat['id'],chat['name'],chat['language']))
            for m in chat['messages']:
                m=dict(m); m['timestamp']=(anchor+timedelta(hours=m.pop('hours_offset'))).isoformat()
                c.execute('INSERT OR IGNORE INTO assistant_messages VALUES(?,?,?,?,?)',(m['id'],chat['id'],m['timestamp'],m['direction'],json.dumps(m,ensure_ascii=False)))
    def summary(c,day,preview=False):
        cutoff=datetime.combine(day,datetime.min.time(),TZ).replace(hour=17)
        if preview: cutoff=min(cutoff,now())
        rows=chats(c,cutoff)
        rows=[r for r in rows if any(parse_time(m['timestamp'])<=cutoff for m in r['messages'])]
        same_day=lambda m: parse_time(m['timestamp']).date()==day and parse_time(m['timestamp'])<=cutoff
        counts=dict(new_enquiries=sum(min(parse_time(m['timestamp']) for m in r['messages']).date()==day for r in rows),
                    replied_customers=sum(any(same_day(m) and m['direction']=='inbound' for m in r['messages']) for r in rows),
                    unanswered_customers=sum(r['analysis']['unanswered'] for r in rows),
                    quotations=sum(any(same_day(m) and any(e['id']==m['id'] and e['kind'] in ['Formal quotation PDF candidate','Informal offer candidate'] and m['direction']=='outbound' for e in r['analysis']['evidence']) for m in r['messages']) for r in rows),
                    followups=sum(r['analysis']['needs_followup'] for r in rows), urgent_opportunities=sum(r['analysis']['urgent'] for r in rows))
        return dict(counts=counts,urgent=[r['name'] for r in rows if r['analysis']['urgent']],waiting=[r['name'] for r in rows if r['analysis']['state']=='Waiting for quotation'])
    def generate_due():
        stamp=now()
        if stamp.hour<17: return False
        day=stamp.date()
        with db() as c:
            if not c.execute('SELECT id FROM assistant_chats LIMIT 1').fetchone(): return False
            if c.execute('SELECT day FROM assistant_summaries WHERE day=?',(str(day),)).fetchone(): return False
            payload=summary(c,day)
            inserted=c.execute('INSERT OR IGNORE INTO assistant_summaries VALUES(?,?,?)',(str(day),stamp.replace(hour=17,minute=0,second=0,microsecond=0).isoformat(),json.dumps(payload,ensure_ascii=False))).rowcount
        return bool(inserted)
    @app.route('/assistant',methods=['GET','POST'])
    @login_required
    def assistant():
        if request.method=='POST':
            f=request.form
            with db() as c:
                if f.get('action')=='paste':
                    try:
                        name=f.get('name','').strip(); language=f.get('language')
                        if not name or len(name)>200: raise ValueError('请填写客户名称，最多 200 个字符。')
                        if language not in ['en','zh','ms']: raise ValueError('请选择草稿语言。')
                        end=datetime.fromisoformat(f.get('chat_date','')).replace(tzinfo=TZ)
                        if end>now(): raise ValueError('聊天时间不能晚于现在。')
                        messages=parse_pasted_chat(f.get('conversation',''),end)
                        chat_id='paste-'+uuid.uuid4().hex
                        c.execute('INSERT INTO assistant_chats(id,name,language) VALUES(?,?,?)',(chat_id,name,language))
                        c.execute('INSERT INTO assistant_imports VALUES(?,?)',(chat_id,now().isoformat()))
                        for m in messages:
                            c.execute('INSERT INTO assistant_messages VALUES(?,?,?,?,?)',(m['id'],chat_id,m['timestamp'],m['direction'],json.dumps(m,ensure_ascii=False)))
                        flash('聊天已保存并分析。请审核建议；没有发送任何消息。')
                    except ValueError as e:
                        flash(str(e) or '请填写有效的聊天日期和时间。')
                elif f.get('action')=='samples': import_samples(c); flash('Fictional chats loaded. Your existing CRM records were not changed.')
                else:
                    chat=next((r for r in chats(c) if r['id']==f.get('chat_id')),None)
                    if not chat: abort(404)
                    if f.get('action')=='review':
                        if f.get('category') not in CATEGORIES or f.get('state') not in STATES: abort(400)
                        c.execute('UPDATE assistant_chats SET category_override=?,state_override=? WHERE id=?',(f['category'],f['state'],chat['id']))
                        flash('Review saved. Existing CRM quotations remain unchanged.')
                    elif f.get('action')=='draft':
                        lang=f.get('language')
                        if lang not in ['en','zh','ms']: abort(400)
                        pending=c.execute("SELECT id FROM assistant_queue WHERE chat_id=? AND status='Pending'",(chat['id'],)).fetchone()
                        if not pending:
                            c.execute('INSERT INTO assistant_queue(chat_id,language,text,created) VALUES(?,?,?,?)',(chat['id'],lang,draft(chat['name'],chat['effective']['category'],chat['effective']['state'],lang),now().isoformat()))
                        flash('Draft is in the approval queue. Nothing was sent.')
                    else: abort(400)
            return redirect(url_for('assistant'))
        generate_due()
        with db() as c: rows=chats(c)
        return render_template('assistant.html',rows=rows,categories=CATEGORIES,states=STATES,chat_date=now().strftime('%Y-%m-%dT%H:%M'))
    @app.route('/assistant/queue',methods=['GET','POST'])
    @login_required
    def assistant_queue():
        if request.method=='POST':
            f=request.form; action=f.get('action'); text=f.get('text','').strip()
            if action not in ['approve','reject'] or (action=='approve' and not 1<=len(text)<=1000): abort(400)
            with db() as c:
                changed=c.execute("UPDATE assistant_queue SET text=?,status=?,reviewer=?,reviewed=? WHERE id=? AND status='Pending'",(text,'Approved' if action=='approve' else 'Rejected',session['user'],now().isoformat(),f.get('id'))).rowcount
                if not changed: abort(409)
            flash('Review recorded. Live sending is disabled; approval does not send a message.')
            return redirect(url_for('assistant_queue'))
        with db() as c: rows=c.execute('SELECT q.*,c.name FROM assistant_queue q JOIN assistant_chats c ON c.id=q.chat_id ORDER BY q.id DESC').fetchall()
        return render_template('assistant_queue.html',rows=rows)
    @app.get('/assistant/summary')
    @login_required
    def assistant_summary():
        generate_due()
        with db() as c:
            rows=[dict(r)|dict(data=json.loads(r['payload'])) for r in c.execute('SELECT * FROM assistant_summaries ORDER BY day DESC')]
            preview=summary(c,now().date(),preview=True)
        return render_template('assistant_summary.html',rows=rows,preview=preview)
    @app.cli.command('assistant-summary')
    def summary_command():
        click.echo('5 PM summary saved.' if generate_due() else 'No chats, not due yet, or already saved today.')
    app.assistant_summary=generate_due
