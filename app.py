import json, sqlite3, re, math
from statistics import NormalDist
from datetime import datetime, timezone, date
from pathlib import Path
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API='https://clinicaltrials.gov/api/v2/studies'; DB=Path(__file__).with_name('clinical_trials.db'); PAGE_SIZE=1000
FIELDS=','.join(['NCTId','BriefTitle','OverallStatus','StudyType','Phase','StartDate','PrimaryCompletionDate','CompletionDate','StudyFirstPostDate','LastUpdatePostDate','LeadSponsorName','LeadSponsorClass','Condition','InterventionName','InterventionType','EnrollmentCount','EnrollmentType','PrimaryOutcomeMeasure','SecondaryOutcomeMeasure','LocationCountry'])
# Broad, non-exhaustive taxonomy. Conditions may span multiple areas.
TA_RULES={
'Oncology & Hematologic Malignancies':['cancer','carcinoma','tumor','tumour','lymphoma','leukemia','myeloma','melanoma','sarcoma','neoplasm','glioblastoma','malignancy'],
'Neurology & Neurodegeneration':['alzheimer','parkinson','epilep','multiple sclerosis','huntington','amyotrophic','stroke','migraine','neuropath','brain injury','dementia','ataxia','seizure'],
'Psychiatry & Mental Health':['depression','schizophrenia','bipolar','anxiety','ptsd','psychiatric','psychosis','suicid','ocd'],
'Immunology & Autoimmune':['arthritis','lupus','psoriasis','crohn','colitis','autoimmune','inflamm','atopic dermatitis','scleroderma'],
'Cardiovascular':['heart','cardiac','cardiovascular','hypertension','coronary','atherosclerosis','atrial fibrillation','heart failure'],
'Infectious Disease':['infection','covid','influenza','hiv','hepatitis','tuberculosis','malaria','sepsis','bacterial','viral','fungal'],
'Endocrinology & Metabolic':['diabetes','obesity','metabolic','thyroid','endocrine','hyperlipid','dyslipid','osteoporosis'],
'Respiratory & Pulmonary':['asthma','copd','pulmonary','lung disease','respiratory','cystic fibrosis','bronchiectasis'],
'Rare & Genetic Disorders':['rare disease','genetic disorder','muscular dystrophy','hemophilia','sickle cell','lysosomal','spinal muscular atrophy','fabry','gaucher'],
'Ophthalmology':['retina','macular','glaucoma','ocular','ophthalm','eye disease','uveitis'],
'Nephrology & Urology':['kidney','renal','nephro','bladder','urinary','prostate hyperplasia','urolog'],
'Gastroenterology & Hepatology':['gastro','bowel','liver','cirrhosis','pancreatitis','celiac','digestive','nash','mash'],
'Dermatology':['eczema','acne','alopecia','dermat','vitiligo','hidradenitis','skin disease'],
'Musculoskeletal & Orthopedics':['osteoarthritis','fracture','bone','cartilage','tendon','orthopedic','musculoskeletal'],
'Hematology (Non-malignant)':['anemia','anaemia','thrombosis','coagulation','platelet','thalassemia','hemoglobinopathy'],
'Women’s Health & Reproductive':['endometriosis','menopause','fertility','pregnancy','preeclampsia','uterine','ovarian insufficiency','contraception'],
'Maternal, Neonatal & Pediatric':['neonatal','newborn','prematurity','preterm','pediatric','infant'],
'Men’s Health':['erectile dysfunction','andrology','testosterone deficiency','male infertility'],
'Otolaryngology (ENT)':['hearing loss','tinnitus','otitis','sinusitis','rhinitis','vestibular'],
'Dentistry & Oral Health':['periodontal','dental','oral health','gingivitis','tooth'],
'Pain & Anesthesiology':['chronic pain','fibromyalgia','analgesia','anesthesia','nocicept'],
'Critical Care & Emergency Medicine':['critical illness','intensive care','shock','acute respiratory distress','trauma'],
'Transplantation':['transplant','graft-versus-host','organ rejection'],
'Allergy':['allerg','anaphylaxis','urticaria'],
'Sleep Medicine':['sleep apnea','insomnia','narcolepsy','sleep disorder'],
'Nutrition & Obesity':['malnutrition','nutrition','vitamin deficiency','weight management'],
'Preventive Medicine & Public Health':['prevention','screening','vaccination','public health'],
'Pediatrics & Adolescent Medicine':['childhood disease','adolescent','pediatric condition'],
'Genetics & Inborn Errors of Metabolism':['inborn error','chromosomal','genetic syndrome','metabolic disorder'],
'Rheumatology':['rheumatoid','vasculitis','spondylitis','myositis','gout'],
'Vascular Medicine':['peripheral artery','venous insufficiency','deep vein thrombosis','pulmonary embolism'],
'Geriatrics & Aging':['frailty','aging','geriatric'],
'Rehabilitation & Physical Medicine':['rehabilitation','physical therapy','motor recovery'],
'Occupational & Environmental Health':['occupational','environmental exposure','poisoning'],
'Sexual Health':['sexual dysfunction','sexually transmitted'],
'Palliative & Supportive Care':['palliative','hospice','supportive care'],
'Medical Imaging & Diagnostics':['diagnostic imaging','radiology','imaging diagnosis'],
'Clinical Pharmacology & Toxicology':['drug interaction','toxicity','overdose'],
'Health Services & Implementation':['health services','implementation science','healthcare delivery'],
'Unmapped registry condition':[]
}
MODALITY_OPTIONS=['Small molecule','Monoclonal antibody','Bispecific/multispecific antibody','Antibody-drug conjugate (ADC)','Fc fusion / engineered fusion protein','Recombinant protein / enzyme','Peptide therapeutic','Oligonucleotide therapeutic (ASO / siRNA)','mRNA / RNA therapeutic','Gene therapy (viral vector)','Gene editing','Engineered immune cell therapy (CAR-T / TCR / NK)','Stem cell / regenerative therapy','Oncolytic virus','Vaccine','Microbiome therapy','Radiopharmaceutical','Phage therapy','Biologic (subtype not specified)','Drug (modality not specified)','Medical device','Procedure / surgery','Radiation','Behavioral / digital therapeutic','Diagnostic / imaging','Dietary supplement','Combination therapy / multimodal','Not specified in registry']


def conn(): return sqlite3.connect(DB)
def init_db():
    with conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS trials (nct_id TEXT PRIMARY KEY,title TEXT,status TEXT,study_type TEXT,phases TEXT,start_date TEXT,primary_completion_date TEXT,completion_date TEXT,first_posted TEXT,last_updated TEXT,sponsor TEXT,sponsor_class TEXT,conditions TEXT,interventions TEXT,intervention_types TEXT,enrollment INTEGER,enrollment_type TEXT,primary_outcomes TEXT,countries TEXT,fetched_at TEXT,raw_json TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS snapshots (snapshot_date TEXT,nct_id TEXT,status TEXT,enrollment INTEGER,primary_completion_date TEXT,completion_date TEXT,primary_outcomes TEXT,last_updated TEXT,PRIMARY KEY(snapshot_date,nct_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS landscape_trials (disease_query TEXT,nct_id TEXT PRIMARY KEY,payload_json TEXT,fetched_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS endpoints (disease_query TEXT,nct_id TEXT,outcome_type TEXT,measure TEXT,description TEXT,time_frame TEXT,PRIMARY KEY(disease_query,nct_id,outcome_type,measure,time_frame))''')
        c.execute('''CREATE TABLE IF NOT EXISTS changes (detected_at TEXT,nct_id TEXT,change_type TEXT,severity TEXT,field_name TEXT,old_value TEXT,new_value TEXT,description TEXT,PRIMARY KEY(detected_at,nct_id,change_type,field_name))''')
        c.execute("CREATE TABLE IF NOT EXISTS evidence (id INTEGER PRIMARY KEY AUTOINCREMENT,nct_id TEXT,source_type TEXT,source_title TEXT,source_date TEXT,data_cut_date TEXT,source_url TEXT,reported_n TEXT,follow_up TEXT,endpoints_emphasized TEXT,comparator TEXT,result_notes TEXT,analyst_notes TEXT,created_at TEXT)")
def dig(d,*keys,default=None):
    for k in keys:
        if not isinstance(d,dict): return default
        d=d.get(k)
    return d if d is not None else default
def join_vals(v): return ' | '.join(str(x) for x in v if x not in (None,''))
def normalize(s):
    p=s.get('protocolSection',{}); ident=p.get('identificationModule',{}); status=p.get('statusModule',{}); design=p.get('designModule',{}); sponsor=p.get('sponsorCollaboratorsModule',{}).get('leadSponsor',{}); cond=p.get('conditionsModule',{}); arms=p.get('armsInterventionsModule',{}); outcomes=p.get('outcomesModule',{}); loc=p.get('contactsLocationsModule',{}).get('locations',[]); ints=arms.get('interventions',[]) or []; primary=outcomes.get('primaryOutcomes',[]) or []
    return {'nct_id':ident.get('nctId'),'title':ident.get('briefTitle'),'status':status.get('overallStatus'),'study_type':design.get('studyType'),'phases':join_vals(design.get('phases',[]) or []),'start_date':dig(status,'startDateStruct','date'),'primary_completion_date':dig(status,'primaryCompletionDateStruct','date'),'completion_date':dig(status,'completionDateStruct','date'),'first_posted':dig(status,'studyFirstPostDateStruct','date'),'last_updated':dig(status,'lastUpdatePostDateStruct','date'),'sponsor':sponsor.get('name'),'sponsor_class':sponsor.get('class'),'conditions':join_vals(cond.get('conditions',[]) or []),'interventions':join_vals([x.get('name') for x in ints]),'intervention_types':join_vals(sorted({x.get('type') for x in ints if x.get('type')})),'enrollment':dig(design,'enrollmentInfo','count'),'enrollment_type':dig(design,'enrollmentInfo','type'),'primary_outcomes':join_vals([x.get('measure') for x in primary]),'countries':join_vals(sorted({x.get('country') for x in loc if x.get('country')})),'fetched_at':datetime.now(timezone.utc).isoformat(),'raw_json':json.dumps(s)}
def fetch_year(year,progress=None):
    term=f'AREA[StudyType]INTERVENTIONAL AND AREA[StartDate]RANGE[01/01/{year}, 12/31/{year}]'; token=None; rows=[]; total=None
    while True:
        params={'format':'json','pageSize':PAGE_SIZE,'query.term':term,'fields':FIELDS};
        if token: params['pageToken']=token
        else: params['countTotal']='true'
        r=requests.get(API,params=params,timeout=60); r.raise_for_status(); payload=r.json(); total=total or payload.get('totalCount'); rows.extend(normalize(s) for s in payload.get('studies',[]))
        if progress and total: progress.progress(min(len(rows)/total,1),text=f'Downloaded {len(rows):,} of {total:,} trials')
        token=payload.get('nextPageToken')
        if not token: break
    return rows,total

def fetch_disease(disease,progress=None):
    token=None; studies=[]; total=None
    while True:
        params={'format':'json','pageSize':PAGE_SIZE,'query.cond':disease,'filter.overallStatus':'RECRUITING|NOT_YET_RECRUITING|ACTIVE_NOT_RECRUITING|ENROLLING_BY_INVITATION','fields':FIELDS}
        if token: params['pageToken']=token
        else: params['countTotal']='true'
        r=requests.get(API,params=params,timeout=60); r.raise_for_status(); payload=r.json(); total=total or payload.get('totalCount'); studies.extend(payload.get('studies',[]))
        if progress and total: progress.progress(min(len(studies)/total,1),text=f'Downloaded {len(studies):,} of {total:,} active trials')
        token=payload.get('nextPageToken')
        if not token: break
    return studies,total

def fetch_all_disease_trials(disease, progress=None):
    """Fetch the complete interventional study universe for a condition, across all years/statuses."""
    disease=(disease or '').strip()
    if not disease:
        return [],0
    token=None; studies=[]; total=None
    while True:
        params={
            'format':'json',
            'pageSize':PAGE_SIZE,
            'query.cond':disease,
            'query.term':'AREA[StudyType]INTERVENTIONAL',
            'fields':FIELDS,
        }
        if token: params['pageToken']=token
        else: params['countTotal']='true'
        r=requests.get(API,params=params,timeout=60); r.raise_for_status(); payload=r.json()
        if total is None: total=payload.get('totalCount')
        studies.extend(payload.get('studies',[]))
        if progress and total:
            progress.progress(min(len(studies)/total,1),text=f'Downloaded {len(studies):,} of {total:,} interventional trials')
        token=payload.get('nextPageToken')
        if not token: break
    return [normalize(x) for x in studies], total

def fetch_trial_detail(nct_id):
    nct_id=(nct_id or '').strip().upper()
    if not re.fullmatch(r'NCT\d{8}',nct_id): raise ValueError('Enter an NCT ID such as NCT04120493.')
    r=requests.get(f'{API}/{nct_id}',params={'format':'json'},timeout=60); r.raise_for_status(); return r.json()

def trial_intelligence(study):
    p=study.get('protocolSection',{}); ident=p.get('identificationModule',{}); status=p.get('statusModule',{}); design=p.get('designModule',{}); elig=p.get('eligibilityModule',{}); arms=p.get('armsInterventionsModule',{}); outcomes=p.get('outcomesModule',{}); sponsor=p.get('sponsorCollaboratorsModule',{}).get('leadSponsor',{})
    di=design.get('designInfo',{}) or {}; enroll=design.get('enrollmentInfo',{}) or {}; ints=arms.get('interventions',[]) or []; armgroups=arms.get('armGroups',[]) or []
    primary=outcomes.get('primaryOutcomes',[]) or []; secondary=outcomes.get('secondaryOutcomes',[]) or []
    allocation=di.get('allocation') or 'Not reported'; model=di.get('interventionModel') or 'Not reported'; masking=(di.get('maskingInfo',{}) or {}).get('masking') or 'Not reported'; purpose=di.get('primaryPurpose') or 'Not reported'
    sex=elig.get('sex') or 'Not reported'; minage=elig.get('minimumAge') or 'Not reported'; maxage=elig.get('maximumAge') or 'Not reported'; healthy=elig.get('healthyVolunteers')
    flags=[]
    n=enroll.get('count')
    if isinstance(n,(int,float)) and n<50: flags.append(('Small planned enrollment',f'Planned enrollment is {n}. Small samples can make estimates imprecise and subgroup analyses especially fragile.'))
    if allocation=='NA' or allocation=='Not reported': flags.append(('No randomized allocation reported','Investigate whether the design is single-arm, non-randomized, or uses another comparison strategy.'))
    if masking in {'NONE','Not reported'}: flags.append(('Open-label / masking not reported','Assess susceptibility of subjective outcomes and investigator/participant assessments to expectation bias.'))
    if len(primary)>1: flags.append(('Multiple primary outcomes',f'{len(primary)} primary outcomes are registered. Review multiplicity handling and whether success requires one or all endpoints.'))
    if primary and any(any(k in ((o.get('measure','')+' '+o.get('description','')).lower()) for k in ['biomarker','plasma','serum','protein','rna','dna','imaging','mri']) for o in primary): flags.append(('Biomarker/imaging primary outcome','Determine how well the primary measure is validated as a surrogate for patient-relevant clinical benefit.'))
    if not armgroups or len(armgroups)==1: flags.append(('Single-arm structure possible','Only one or no arm group is registered. Determine whether efficacy interpretation relies on baseline change, natural history, or an external control.'))
    return {'nct_id':ident.get('nctId'),'title':ident.get('briefTitle'),'official_title':ident.get('officialTitle'),'status':status.get('overallStatus'),'phase':join_vals(design.get('phases',[]) or []),'sponsor':sponsor.get('name'),'conditions':join_vals((p.get('conditionsModule',{}) or {}).get('conditions',[]) or []),'interventions':join_vals([x.get('name') for x in ints]),'enrollment':n,'enrollment_type':enroll.get('type'),'allocation':allocation,'intervention_model':model,'masking':masking,'primary_purpose':purpose,'arms':len(armgroups),'sex':sex,'minimum_age':minage,'maximum_age':maxage,'healthy_volunteers':healthy,'criteria':elig.get('eligibilityCriteria') or 'Not reported','primary':primary,'secondary':secondary,'flags':flags}



def endpoint_classification(outcome):
    text=((outcome.get('measure') or '')+' '+(outcome.get('description') or '')).lower()
    if any(k in text for k in ['overall survival','progression-free','event-free survival','mortality','death']): return 'Clinical outcome / time-to-event'
    if any(k in text for k in ['quality of life','questionnaire','scale','score','functional','function','symptom','pain','response rate','remission']): return 'Clinical / functional'
    if any(k in text for k in ['mri','pet','ct scan','imaging','radiographic']): return 'Imaging / radiographic'
    if any(k in text for k in ['biomarker','plasma','serum','blood level','protein','rna','dna','nfl','neurofilament','pharmacokinetic','auc','cmax']): return 'Biomarker / laboratory'
    if any(k in text for k in ['adverse event','toxicity','safety','tolerability','dose limiting']): return 'Safety / tolerability'
    return 'Unclassified — inspect manually'

def split_eligibility(criteria):
    text=criteria or ''
    low=text.lower(); inc=text; exc=''
    markers=['exclusion criteria','exclusion:','exclusion criteria:']
    pos=-1
    for m in markers:
        q=low.find(m)
        if q!=-1 and (pos==-1 or q<pos): pos=q
    if pos!=-1:
        inc=text[:pos].strip(); exc=text[pos:].strip()
    return inc or 'Not separately reported', exc or 'Not separately reported'

def v06a_analysis(study):
    ti=trial_intelligence(study)
    p=study.get('protocolSection',{}) or {}; design=p.get('designModule',{}) or {}; di=design.get('designInfo',{}) or {}; arms=(p.get('armsInterventionsModule',{}) or {}).get('armGroups',[]) or []
    mask=(di.get('maskingInfo',{}) or {})
    design_rows=[
        ('Phase',ti['phase'] or 'Not reported'),('Allocation',ti['allocation']),('Intervention model',ti['intervention_model']),
        ('Masking',ti['masking']),('Who is masked',join_vals(mask.get('whoMasked',[]) or []) or 'Not reported'),
        ('Primary purpose',ti['primary_purpose']),('Number of registered arms',ti['arms']),('Enrollment',ti['enrollment'] if ti['enrollment'] is not None else 'Not reported'),
        ('Enrollment type',ti['enrollment_type'] or 'Not reported')
    ]
    dqs=[]
    if ti['allocation']!='RANDOMIZED': dqs.append('What counterfactual supports causal interpretation if allocation is not randomized?')
    if str(ti['masking']).upper() in {'NONE','NOT REPORTED'}: dqs.append('Could knowledge of treatment influence subjective endpoint assessment, adherence, or investigator behavior?')
    if ti['arms']<=1: dqs.append('Does efficacy interpretation rely on within-patient change, natural history, or an external control?')
    if isinstance(ti['enrollment'],(int,float)) and ti['enrollment']<100: dqs.append('Is the sample large enough for stable treatment-effect estimates and any planned subgroup analyses?')
    eps=[]
    for typ,key in [('Primary','primary'),('Secondary','secondary')]:
        for i,o in enumerate(ti[key],1): eps.append({'Hierarchy':typ,'#':i,'Registered measure':o.get('measure',''),'Time frame':o.get('timeFrame',''),'Derived class':endpoint_classification(o),'Registered description':o.get('description','')})
    eq=[]
    if len(ti['primary'])>1: eq.append(f"There are {len(ti['primary'])} registered primary outcomes. How is multiplicity controlled and what constitutes trial success?")
    if any(endpoint_classification(o).startswith(('Biomarker','Imaging')) for o in ti['primary']): eq.append('If a biomarker or imaging measure is primary, how well is it validated as a surrogate for patient-relevant benefit?')
    if ti['primary']: eq.append('Is the primary endpoint clinically meaningful, sensitive to change, and measured at an appropriate time point for this disease?')
    if ti['secondary']: eq.append('Which secondary endpoints are confirmatory versus exploratory, and is multiplicity adjustment prespecified?')
    inc,exc=split_eligibility(ti['criteria'])
    pop_rows=[('Conditions',ti['conditions']),('Sex',ti['sex']),('Minimum age',ti['minimum_age']),('Maximum age',ti['maximum_age']),('Healthy volunteers',str(ti['healthy_volunteers']) if ti['healthy_volunteers'] is not None else 'Not reported'),('Enrollment',ti['enrollment'] if ti['enrollment'] is not None else 'Not reported')]
    pqs=['Do the eligibility criteria select a narrower or earlier/later-stage population than typical real-world patients?','Are important comorbidities or prior therapies excluded in ways that could limit generalizability?','Are biomarker, genetic, severity, or prior-treatment requirements enriching for patients more likely to respond?','Will the enrolled population be comparable to the population used for any external or historical control?']
    return ti,design_rows,dqs,pd.DataFrame(eps),eq,pop_rows,inc,exc,pqs

def save_disease(disease,studies):
    now=datetime.now(timezone.utc).isoformat(); rows=[]; eps=[]
    with conn() as c:
        c.execute('DELETE FROM endpoints WHERE disease_query=?',(disease,))
        for study in studies:
            r=normalize(study); rows.append(r)
            c.execute('INSERT OR REPLACE INTO landscape_trials VALUES (?,?,?,?)',(disease,r['nct_id'],json.dumps(study),now))
            outs=dig(study,'protocolSection','outcomesModule',default={}) or {}
            for typ,key in [('Primary','primaryOutcomes'),('Secondary','secondaryOutcomes')]:
                for o in outs.get(key,[]) or []:
                    eps.append((disease,r['nct_id'],typ,o.get('measure') or '',o.get('description') or '',o.get('timeFrame') or ''))
        if eps:c.executemany('INSERT OR REPLACE INTO endpoints VALUES (?,?,?,?,?,?)',eps)
    return len(rows),len(eps)

def load_disease(disease):
    with conn() as c:
        raw=pd.read_sql_query('SELECT payload_json FROM landscape_trials WHERE disease_query=?', c, params=(disease,))
        ep=pd.read_sql_query('SELECT * FROM endpoints WHERE disease_query=?', c, params=(disease,))
    if raw.empty:return pd.DataFrame(),ep
    df=pd.DataFrame([normalize(json.loads(x)) for x in raw.payload_json])
    for col in ['start_date','primary_completion_date','completion_date','last_updated']: df[col+'_dt']=pd.to_datetime(df[col],errors='coerce')
    df['therapeutic_area']=df.conditions.apply(classify_ta); df['modality']=df.apply(modality,axis=1)
    return df,ep

def _clean(v):
    return '' if v is None else str(v).strip()
def _date_shift_days(old,new):
    try: return int((pd.to_datetime(new)-pd.to_datetime(old)).days)
    except Exception: return None
def detect_changes(previous,current,detected_at):
    out=[]
    if not previous:return out
    def add(kind,severity,field,old,new,desc): out.append((detected_at,current['nct_id'],kind,severity,field,_clean(old),_clean(new),desc))
    old,new=previous.get('status'),current.get('status')
    if _clean(old)!=_clean(new):
        sev='High' if new in {'SUSPENDED','TERMINATED','WITHDRAWN'} else 'Medium'; add('Status change',sev,'status',old,new,f'Status changed from {old or "—"} to {new or "—"}.')
    old,new=previous.get('enrollment'),current.get('enrollment')
    if _clean(old)!=_clean(new) and old is not None and new is not None:
        try:
            pct=(float(new)-float(old))/max(abs(float(old)),1)*100; sev='High' if pct<=-20 else ('Medium' if abs(pct)>=10 else 'Low'); add('Enrollment change',sev,'enrollment',old,new,f'Enrollment changed from {old} to {new} ({pct:+.1f}%).')
        except Exception: add('Enrollment change','Medium','enrollment',old,new,f'Enrollment changed from {old} to {new}.')
    for field,label in [('primary_completion_date','Primary completion'),('completion_date','Study completion')]:
        old,new=previous.get(field),current.get(field)
        if _clean(old)!=_clean(new) and old and new:
            days=_date_shift_days(old,new); sev='High' if days is not None and days>=90 else ('Medium' if days is not None and abs(days)>=30 else 'Low'); direction='delayed' if days and days>0 else 'moved earlier' if days and days<0 else 'changed'; extra=f' by {abs(days)} days' if days else ''; add('Date change',sev,field,old,new,f'{label} {direction}{extra}: {old} → {new}.')
    old,new=previous.get('primary_outcomes'),current.get('primary_outcomes')
    if _clean(old)!=_clean(new) and (old or new): add('Endpoint change','High','primary_outcomes',old,new,'Primary outcome measure text changed.')
    return out
def save(rows):
    if not rows:return 0
    cols=list(rows[0]); sql=f"INSERT OR REPLACE INTO trials ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})"; snap=datetime.now(timezone.utc).date().isoformat(); detected=datetime.now(timezone.utc).isoformat(timespec='seconds'); changes=[]
    with conn() as c:
        keys=['status','enrollment','primary_completion_date','completion_date','primary_outcomes','last_updated']
        for r in rows:
            pr=c.execute('SELECT status,enrollment,primary_completion_date,completion_date,primary_outcomes,last_updated FROM trials WHERE nct_id=?',(r['nct_id'],)).fetchone(); prev=dict(zip(keys,pr)) if pr else None; changes.extend(detect_changes(prev,r,detected))
        c.executemany(sql,[[r.get(k) for k in cols] for r in rows]); c.executemany('INSERT OR REPLACE INTO snapshots (snapshot_date,nct_id,status,enrollment,primary_completion_date,completion_date,primary_outcomes,last_updated) VALUES (?,?,?,?,?,?,?,?)',[(snap,r['nct_id'],r['status'],r['enrollment'],r['primary_completion_date'],r['completion_date'],r['primary_outcomes'],r['last_updated']) for r in rows])
        if changes:c.executemany('INSERT OR REPLACE INTO changes VALUES (?,?,?,?,?,?,?,?)',changes)
    return len(changes)
def load_changes(year):
    with conn() as c: ch=pd.read_sql_query('SELECT c.*,t.title,t.sponsor,t.conditions,t.interventions,t.phases,t.start_date FROM changes c LEFT JOIN trials t ON c.nct_id=t.nct_id',c)
    if ch.empty:return ch
    ch['detected_dt']=pd.to_datetime(ch.detected_at,errors='coerce'); ch['start_dt']=pd.to_datetime(ch.start_date,errors='coerce'); return ch[ch.start_dt.dt.year==year].copy()
def add_demo_change(year):
    df=load_year(year)
    if df.empty:return False
    r=df.iloc[0]; now=datetime.now(timezone.utc).isoformat(timespec='seconds'); old=100 if pd.isna(r.enrollment) else int(r.enrollment); demo=(now,r.nct_id,'Enrollment change','Medium','enrollment',str(old),str(old+25),'DEMO signal: enrollment changed. This row is only for testing the V0.3 interface.')
    with conn() as c:c.execute('INSERT OR REPLACE INTO changes VALUES (?,?,?,?,?,?,?,?)',demo)
    return True
def load_year(year):
    with conn() as c: df=pd.read_sql_query('SELECT * FROM trials',c)
    if df.empty:return df
    for c in ['start_date','primary_completion_date','completion_date','last_updated']: df[c+'_dt']=pd.to_datetime(df[c],errors='coerce')
    return df[df.start_date_dt.dt.year==year].copy()
def explode_counts(df,col,top=15):
    if df.empty:return pd.DataFrame(columns=[col,'count'])
    s=df[col].fillna('').str.split(' \\| ').explode().str.strip(); s=s[s.ne('')]; return s.value_counts().head(top).rename_axis(col).reset_index(name='count')
def classify_ta(x):
    t=(x or '').lower()
    matches=[area for area,terms in TA_RULES.items() if terms and any(term in t for term in terms)]
    return ' | '.join(matches) if matches else ('Registry condition: ' + ' / '.join(z.strip() for z in str(x or '').split(' | ') if z.strip()) if str(x or '').strip() else 'Condition not specified in registry')

def modality(row):
    names=str(row.get('interventions','') or '').lower()
    kinds=str(row.get('intervention_types','') or '').lower()
    t=names+' '+kinds
    found=[]
    def add(label, terms):
        if any(term in t for term in terms) and label not in found: found.append(label)
    add('Gene editing',['crispr','gene editing','base editing','prime editing','zinc finger nuclease','talen'])
    add('Gene therapy (viral vector)',['gene therapy','gene transfer','aav','adeno-associated virus','lentiviral','adenoviral vector'])
    add('Engineered immune cell therapy (CAR-T / TCR / NK)',['car-t','car t','car t-cell','car-t cell','tcr-t','tcr t','nk cell therapy','cell therapy','cellular therapy'])
    add('Stem cell / regenerative therapy',['stem cell','mesenchymal stromal','regenerative cell','ipsc'])
    add('Antibody-drug conjugate (ADC)',['antibody-drug conjugate','antibody drug conjugate','adc '])
    add('Bispecific/multispecific antibody',['bispecific','trispecific','multispecific','bite '])
    add('Monoclonal antibody',['monoclonal',' mab','mab ','-mab','antibody'])
    add('Fc fusion / engineered fusion protein',['fc fusion','fusion protein','immunoadhesin'])
    add('Oligonucleotide therapeutic (ASO / siRNA)',['sirna','small interfering rna','antisense','oligonucleotide','aso ','rnai'])
    add('mRNA / RNA therapeutic',['mrna','messenger rna','rna therapy','rna therapeutic'])
    add('Recombinant protein / enzyme',['recombinant protein','enzyme replacement','therapeutic protein','recombinant enzyme'])
    add('Peptide therapeutic',['peptide'])
    add('Oncolytic virus',['oncolytic virus','oncolytic viral'])
    add('Vaccine',['vaccine','vaccination'])
    add('Microbiome therapy',['microbiome','fecal microbiota','faecal microbiota','live biotherapeutic'])
    add('Radiopharmaceutical',['radiopharmaceutical','radioligand','radioisotope therapy'])
    add('Phage therapy',['bacteriophage','phage therapy'])
    add('Diagnostic / imaging',['diagnostic','imaging agent','contrast agent'])
    add('Radiation',['radiation','radiotherapy'])
    add('Behavioral / digital therapeutic',['behavioral','digital therapeutic','psychotherapy','cognitive behavioral'])
    add('Medical device',['device'])
    add('Procedure / surgery',['procedure','surgery','surgical'])
    add('Dietary supplement',['dietary supplement','supplement'])
    if not found:
        if 'biological' in kinds: found=['Biologic (subtype not specified)']
        elif 'drug' in kinds: found=['Drug (modality not specified)']
        else: found=['Not specified in registry']
    if len(found)>1 and 'Drug (modality not specified)' in found: found.remove('Drug (modality not specified)')
    return ' | '.join(found)

def matches_any(value, selected):
    return any(label in str(value).split(' | ') for label in selected)


def results_intelligence(study):
    rs=study.get('resultsSection',{}) or {}
    pf=rs.get('participantFlowModule',{}) or {}
    base=rs.get('baselineCharacteristicsModule',{}) or {}
    om=rs.get('outcomeMeasuresModule',{}) or {}
    ae=rs.get('adverseEventsModule',{}) or {}
    groups={}
    for module in (pf,base,om,ae):
        for g in module.get('groups',[]) or []:
            gid=g.get('id')
            if gid: groups[gid]=g.get('title') or g.get('description') or gid
    outcomes=om.get('outcomeMeasures',[]) or []
    out_rows=[]; analyses=[]
    for o in outcomes:
        otype=o.get('type','')
        title=o.get('title') or o.get('measure') or ''
        timeframe=o.get('timeFrame','')
        desc=o.get('description','')
        units=o.get('units','')
        for cls in o.get('classes',[]) or []:
            cname=cls.get('title','')
            for cat in cls.get('categories',[]) or []:
                catname=cat.get('title','')
                for m in cat.get('measurements',[]) or []:
                    gid=m.get('groupId','')
                    val=m.get('value')
                    spread=m.get('spread')
                    lower=m.get('lowerLimit')
                    upper=m.get('upperLimit')
                    out_rows.append({'Outcome type':otype,'Outcome':title,'Time frame':timeframe,'Class':cname,'Category':catname,'Arm / group':groups.get(gid,gid),'Value':val,'Spread':spread,'Lower':lower,'Upper':upper,'Units':units,'Description':desc})
        for a in o.get('analyses',[]) or []:
            gids=a.get('groupIds',[]) or []
            analyses.append({'Outcome':title,'Groups compared':' vs '.join(groups.get(g,g) for g in gids),'Method':a.get('method',''),'P value':a.get('pValue'),'Effect estimate':a.get('paramValue'),'Estimate type':a.get('paramType',''),'CI %':a.get('ciPctValue'),'CI lower':a.get('ciLowerLimit'),'CI upper':a.get('ciUpperLimit'),'Notes':a.get('otherAnalysisDescription','')})
    serious=ae.get('seriousEvents',[]) or []
    other=ae.get('otherEvents',[]) or []
    ae_rows=[]
    for label,events in [('Serious',serious),('Other',other)]:
        for ev in events:
            term=ev.get('term',''); organ=ev.get('organSystem','')
            for stt in ev.get('stats',[]) or []:
                gid=stt.get('groupId','')
                ae_rows.append({'Type':label,'Event':term,'Organ system':organ,'Arm / group':groups.get(gid,gid),'Affected':stt.get('numAffected'),'At risk':stt.get('numAtRisk'),'Events':stt.get('numEvents')})
    return {'has_results':bool(rs),'groups':groups,'outcomes':pd.DataFrame(out_rows),'analyses':pd.DataFrame(analyses),'adverse_events':pd.DataFrame(ae_rows),'participant_flow':pf,'baseline':base}

def comparator_intelligence(ti,ri):
    allocation=str(ti.get('allocation') or '').upper(); masking=str(ti.get('masking') or '').upper(); arms=ti.get('arms',0) or 0
    labels=' '.join(str(x).lower() for x in ri.get('groups',{}).values())
    if 'placebo' in labels: ctype='Placebo-controlled'
    elif any(k in labels for k in ['control','standard of care','usual care','active comparator']): ctype='Controlled / active comparator likely'
    elif arms<=1: ctype='Single-arm / no concurrent comparator identified'
    elif allocation=='RANDOMIZED': ctype='Randomized multi-arm comparator'
    else: ctype='Multi-arm comparator; inspect arm definitions'
    qs=[]
    if arms<=1: qs.append('If efficacy is inferred from change from baseline or an external/natural-history cohort, inspect comparability and sensitivity to control assumptions.')
    if 'placebo' not in labels and allocation!='RANDOMIZED': qs.append('No randomized placebo comparator is evident from the structured record; determine what counterfactual is used for efficacy interpretation.')
    if masking in {'NONE','NOT REPORTED'}: qs.append('For subjective clinical outcomes, examine whether open-label assessment could influence observed treatment differences.')
    return ctype,qs


def _candidate_row(source_type, title, date='', url='', notes='', provenance='', external_id='', relevance='Candidate'):
    return {'source_type':source_type,'source_title':title,'source_date':date,'data_cut_date':'','source_url':url,'reported_n':'','follow_up':'','endpoints_emphasized':'','comparator':'','result_notes':notes,'analyst_notes':f'{relevance}. Verify trial linkage and extract the relevant data cut before relying on this source.','provenance':provenance,'external_id':external_id}

def pubmed_search(term, limit=20, relevance='Candidate'):
    base='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    params={'db':'pubmed','term':term,'retmode':'json','retmax':limit,'sort':'pub date','tool':'ClinicalTrialIntelligence','email':'local-app@example.com'}
    r=requests.get(base+'esearch.fcgi',params=params,timeout=30,headers={'User-Agent':'ClinicalTrialIntelligence/0.5C.2'})
    r.raise_for_status(); ids=r.json().get('esearchresult',{}).get('idlist',[])
    if not ids: return []
    q={'db':'pubmed','id':','.join(ids),'retmode':'json','tool':'ClinicalTrialIntelligence','email':'local-app@example.com'}
    rr=requests.get(base+'esummary.fcgi',params=q,timeout=30,headers={'User-Agent':'ClinicalTrialIntelligence/0.5C.2'})
    rr.raise_for_status(); data=rr.json().get('result',{})
    rows=[]
    for pmid in ids:
        x=data.get(pmid,{})
        authors=', '.join(a.get('name','') for a in (x.get('authors') or [])[:4])
        rows.append(_candidate_row('Publication',x.get('title','').rstrip('.'),x.get('pubdate',''),f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',f"{x.get('fulljournalname','')}. {authors}".strip('. '),'PubMed / NCBI',pmid,relevance))
    return rows

def europe_pmc_search(term, limit=20, relevance='Candidate'):
    url='https://www.ebi.ac.uk/europepmc/webservices/rest/search'
    r=requests.get(url,params={'query':term,'format':'json','pageSize':limit,'sort':'CITED desc'},timeout=30,headers={'User-Agent':'ClinicalTrialIntelligence/0.5C.2'})
    r.raise_for_status(); rows=[]
    for x in r.json().get('resultList',{}).get('result',[]) or []:
        pmid=str(x.get('pmid','') or ''); pmcid=str(x.get('pmcid','') or '')
        link=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else (f'https://europepmc.org/article/PMC/{pmcid.replace("PMC","")}' if pmcid else 'https://europepmc.org/')
        rows.append(_candidate_row('Publication',x.get('title',''),x.get('firstPublicationDate','') or x.get('pubYear',''),link,x.get('journalTitle',''),'Europe PMC',pmid or pmcid,relevance))
    return rows

def trial_search_terms(stdata, nct_id):
    ps=stdata.get('protocolSection',{}) or {}
    ident=ps.get('identificationModule',{}) or {}; arms=ps.get('armsInterventionsModule',{}) or {}; spons=ps.get('sponsorCollaboratorsModule',{}) or {}
    interventions=[]
    for i in arms.get('interventions',[]) or []:
        name=(i.get('name') or '').strip()
        if name and name.lower() not in {'placebo','sham','usual care'}: interventions.append(name)
    sponsor=((spons.get('leadSponsor') or {}).get('name') or '').strip()
    title=(ident.get('briefTitle') or ident.get('officialTitle') or '').strip()
    terms=[(nct_id,'Exact NCT-ID match')]
    for name in interventions[:3]: terms.append((f'"{name}"',f'Intervention-name search: {name}'))
    if title: terms.append((f'"{title}"', 'Exact study-title search'))
    if sponsor and interventions: terms.append((f'"{interventions[0]}" AND "{sponsor}"', 'Intervention + sponsor search'))
    # preserve order, remove duplicates
    out=[]; seen=set()
    for q,label in terms:
        if q.lower() not in seen: seen.add(q.lower()); out.append((q,label))
    return out

def discover_ctg_evidence(nct_id, stdata=None):
    stdata=stdata or fetch_trial_detail(nct_id); rows=[]
    # Walk the record recursively because references/documents can move between API modules.
    def walk(obj):
        if isinstance(obj,dict):
            if ('citation' in obj or 'pmid' in obj) and (obj.get('citation') or obj.get('pmid')):
                pmid=str(obj.get('pmid','') or ''); cit=obj.get('citation','') or f'ClinicalTrials.gov reference {pmid}'
                rows.append(_candidate_row('Publication',cit,'',f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else f'https://clinicaltrials.gov/study/{nct_id}','Reference embedded in the ClinicalTrials.gov study record.','ClinicalTrials.gov reference',pmid or cit[:80],'Direct registry-linked reference'))
            if ('filename' in obj or 'label' in obj) and any(k in str(obj).lower() for k in ['protocol','statistical analysis','sap','informed consent']):
                label=obj.get('label') or obj.get('filename') or 'Study document'; url=obj.get('url','') or f'https://clinicaltrials.gov/study/{nct_id}'
                rows.append(_candidate_row('Regulatory document',label,obj.get('date',''),url,'Study document embedded in the ClinicalTrials.gov record.','ClinicalTrials.gov study document',obj.get('filename','') or label,'Direct registry-linked document'))
            for v in obj.values(): walk(v)
        elif isinstance(obj,list):
            for v in obj: walk(v)
    walk(stdata)
    return rows

def discover_evidence(nct_id):
    found=[]; errors=[]; diagnostics=[]
    try:
        stdata=fetch_trial_detail(nct_id); diagnostics.append('ClinicalTrials.gov study record: loaded')
        ctg=discover_ctg_evidence(nct_id,stdata); found.extend(ctg); diagnostics.append(f'Registry-linked references/documents: {len(ctg)}')
    except Exception as e:
        stdata={}; errors.append(f'ClinicalTrials.gov discovery: {e}'); diagnostics.append('ClinicalTrials.gov study record: failed')
    terms=trial_search_terms(stdata,nct_id) if stdata else [(nct_id,'Exact NCT-ID match')]
    for idx,(term,label) in enumerate(terms):
        try:
            rows=pubmed_search(term,20,label); found.extend(rows); diagnostics.append(f'PubMed — {label}: {len(rows)}')
        except Exception as e: errors.append(f'PubMed ({label}): {e}')
        # Europe PMC is both a fallback and an independent cross-check. Run exact ID always; broader only until evidence is found.
        if idx==0 or not found:
            try:
                rows=europe_pmc_search(term,20,label); found.extend(rows); diagnostics.append(f'Europe PMC — {label}: {len(rows)}')
            except Exception as e: errors.append(f'Europe PMC ({label}): {e}')
        if len(found)>=30: break
    seen=set(); out=[]
    for r in found:
        key=(r.get('external_id','') or '', (r.get('source_title','') or '').lower().strip())
        if key not in seen: seen.add(key); out.append(r)
    return out,errors,diagnostics

def save_discovered_evidence(nct_id, rec):
    x=dict(rec); x['nct_id']=nct_id
    save_evidence(x)

def save_evidence(rec):
    with conn() as c:
        c.execute("INSERT INTO evidence (nct_id,source_type,source_title,source_date,data_cut_date,source_url,reported_n,follow_up,endpoints_emphasized,comparator,result_notes,analyst_notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (rec['nct_id'].strip().upper(),rec['source_type'],rec['source_title'],rec['source_date'],rec['data_cut_date'],rec['source_url'],rec['reported_n'],rec['follow_up'],rec['endpoints_emphasized'],rec['comparator'],rec['result_notes'],rec['analyst_notes'],datetime.now(timezone.utc).isoformat()))

def load_evidence(nct_id):
    with conn() as c:
        return pd.read_sql_query("SELECT * FROM evidence WHERE nct_id=? ORDER BY COALESCE(NULLIF(data_cut_date,''),source_date), source_date, id",c,params=(nct_id.strip().upper(),))

def evidence_change_prompts(df):
    prompts=[]
    if df.empty or len(df)<2: return prompts
    x=df.copy().fillna('')
    for i in range(1,len(x)):
        a=x.iloc[i-1]; b=x.iloc[i]
        label=f"{a.get('data_cut_date') or a.get('source_date') or 'Earlier source'} → {b.get('data_cut_date') or b.get('source_date') or 'Later source'}"
        for field,name in [('reported_n','Reported N'),('follow_up','Follow-up'),('comparator','Comparator/control'),('endpoints_emphasized','Endpoint emphasis')]:
            old=str(a.get(field,'')).strip(); new=str(b.get(field,'')).strip()
            if old and new and old!=new: prompts.append((label,name,old,new))
    return prompts

st.set_page_config(page_title='Clinical Trial Intelligence Focused',page_icon='🧬',layout='wide');
st.markdown("""<style>
/* Consistent dark charcoal and coral palette, matching the supplied screenshot. */
[data-testid="stAppViewContainer"] {background-color:#0e1117; color:#fafafa;}
[data-testid="stSidebar"] {background-color:#262730;}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:1rem;}
.stTabs [data-baseweb="tab-list"] {border-bottom:1px solid #353740;gap:0.8rem;}
.stTabs [data-baseweb="tab"] {color:#fafafa;}
.stTabs [aria-selected="true"] {color:#ff4b4b!important;}
.stButton > button[kind="primary"], button[data-testid="stBaseButton-primary"] {background:#ff4b4b;color:white;border-color:#ff4b4b;}
.stButton > button[kind="primary"]:hover {background:#ed4141;border-color:#ed4141;}
[data-testid="stMetricValue"] {color:#fafafa;}
</style>""",unsafe_allow_html=True)
init_db(); st.title('Clinical Trial Intelligence · Focused'); st.caption('Market overview · Competitive landscapes · Trial explorer · Trial intelligence · Evidence intelligence')
with st.sidebar:
    year=st.number_input('Start year',2000,2035,2026,1)
    if st.button('Refresh from ClinicalTrials.gov',type='primary',width='stretch'):
        bar=st.progress(0,text='Connecting…')
        try: rows,total=fetch_year(int(year),bar); nchanges=save(rows); bar.empty(); st.success(f'Saved {len(rows):,} trials and detected {nchanges:,} changes.'); st.rerun()
        except Exception as e: bar.empty(); st.error(f'Refresh failed: {e}')

df=load_year(int(year))
if df.empty: st.info('No local data for this year yet. Refresh from ClinicalTrials.gov.'); st.stop()
df['therapeutic_area']=df.conditions.apply(classify_ta); df['modality']=df.apply(modality,axis=1)
with st.sidebar:
    st.divider(); st.subheader('Filters'); st.caption('Areas: matching specialties plus exact registered conditions when no specialty matches. Modalities: explicit evidence only; unspecified mechanisms are labeled as such. These are not independently validated drug annotations.') ; f_phase=st.multiselect('Phase',sorted(explode_counts(df,'phases',100)['phases'].tolist())); f_status=st.multiselect('Status',sorted(df.status.dropna().unique())); f_ta=st.multiselect('Therapeutic area',sorted(set(df.therapeutic_area.fillna('').str.split(' | ').explode().dropna()) - {''})); f_mod=st.multiselect('Modality',MODALITY_OPTIONS); sponsor_q=st.text_input('Sponsor contains'); condition_q=st.text_input('Condition contains'); country_q=st.text_input('Country contains')
f=df.copy()
if f_phase:f=f[f.phases.fillna('').apply(lambda x:any(v in x.split(' | ') for v in f_phase))]
if f_status:f=f[f.status.isin(f_status)]
if f_ta:f=f[f.therapeutic_area.apply(lambda x:matches_any(x,f_ta))]
if f_mod:f=f[f.modality.apply(lambda x:matches_any(x,f_mod))]
if sponsor_q:f=f[f.sponsor.fillna('').str.contains(sponsor_q,case=False,regex=False)]
if condition_q:f=f[f.conditions.fillna('').str.contains(condition_q,case=False,regex=False)]
if country_q:f=f[f.countries.fillna('').str.contains(country_q,case=False,regex=False)]

tab1,tab5,tab6,tab7,tab8=st.tabs(['Market overview','Competitive landscapes','Trial explorer','Trial intelligence','Evidence intelligence'])
with tab1:
    c1,c2,c3,c4=st.columns(4); c1.metric(f'Trials started in {year}',f'{len(f):,}'); c2.metric('Recruiting now',f"{f.status.eq('RECRUITING').sum():,}"); c3.metric('Unique sponsors',f'{f.sponsor.nunique():,}'); c4.metric('Industry sponsored',f"{f.sponsor_class.eq('INDUSTRY').sum():,}")
    a,b=st.columns(2)
    with a:
        m=f.dropna(subset=['start_date_dt']).assign(month=lambda x:x.start_date_dt.dt.to_period('M').astype(str)).groupby('month').size().reset_index(name='trials'); st.plotly_chart(px.line(m,x='month',y='trials',markers=True,title='Trial starts by month'),width='stretch')
    with b:
        ta=explode_counts(f,'therapeutic_area',max(1,len(f)*3)); ta.columns=['area','count']; st.plotly_chart(px.bar(ta,x='count',y='area',orientation='h',title='Therapeutic areas'),width='stretch')
    a,b=st.columns(2)
    with a:
        md=explode_counts(f,'modality',max(1,len(f)*3)); md.columns=['modality','count']; st.plotly_chart(px.bar(md,x='modality',y='count',title='Modality mix'),width='stretch')
    with b:
        ph=explode_counts(f,'phases',10); st.plotly_chart(px.bar(ph,x='phases',y='count',title='Trials by phase'),width='stretch')
with tab5:
    st.subheader('Full Disease Landscape + Endpoint Intelligence')
    st.caption('This view queries active interventional studies for the disease regardless of start year. Primary and secondary outcomes are stored separately with measure, description, and time frame.')
    disease=st.text_input('Disease / condition',value='Huntington Disease',key='landscape_disease')
    if st.button('Load / refresh full disease landscape',type='primary',key='load_disease'):
        bar=st.progress(0,text='Querying ClinicalTrials.gov…')
        try:
            studies,total=fetch_disease(disease.strip(),bar); n,ne=save_disease(disease.strip(),studies); bar.empty(); st.success(f'Saved {n:,} active trials and {ne:,} endpoint records for {disease}.'); st.rerun()
        except Exception as e: bar.empty(); st.error(f'Disease landscape refresh failed: {e}')
    land,eps=load_disease(disease.strip()) if disease.strip() else (pd.DataFrame(),pd.DataFrame())
    if land.empty: st.info('Enter a disease and click “Load / refresh full disease landscape.”')
    else:
        c1,c2,c3,c4,c5=st.columns(5); c1.metric('Active trials',len(land)); c2.metric('Sponsors',land.sponsor.nunique()); c3.metric('Interventions',len(explode_counts(land,'interventions',1000))); c4.metric('Primary endpoints',len(eps[eps.outcome_type=='Primary'])); c5.metric('Secondary endpoints',len(eps[eps.outcome_type=='Secondary']))
        a,b=st.columns(2)
        with a:
            ph=explode_counts(land,'phases',20)
            if not ph.empty: st.plotly_chart(px.bar(ph,x='phases',y='count',title=f'{disease}: active pipeline by phase'),width='stretch')
        with b:
            mm=explode_counts(land,'modality',len(MODALITY_OPTIONS)); mm.columns=['modality','count']; st.plotly_chart(px.bar(mm,x='modality',y='count',title='Pipeline by modality'),width='stretch')
        st.markdown('#### Development landscape')
        land=land.copy(); land['target_mechanism']='Not yet enriched'; land['Trial record']='https://clinicaltrials.gov/study/'+land.nct_id.fillna('')
        st.dataframe(land[['sponsor','interventions','target_mechanism','modality','phases','status','enrollment','primary_outcomes','primary_completion_date','nct_id','Trial record']],hide_index=True,width='stretch',column_config={'Trial record':st.column_config.LinkColumn('Trial',display_text='Open')})
        st.markdown('#### Endpoint explorer')
        et=st.multiselect('Outcome type',['Primary','Secondary'],default=['Primary','Secondary'],key='etype')
        epv=eps[eps.outcome_type.isin(et)].copy() if et else eps.iloc[0:0]
        if not epv.empty:
            meta=land[['nct_id','sponsor','interventions','phases']]; epv=epv.merge(meta,on='nct_id',how='left')
            st.dataframe(epv[['outcome_type','measure','time_frame','description','sponsor','interventions','phases','nct_id']],hide_index=True,width='stretch')
        st.markdown('#### Compare programs side-by-side')
        labels=(land.nct_id.fillna('')+' — '+land.sponsor.fillna('Unknown sponsor')+' — '+land.interventions.fillna('Unnamed intervention')).tolist()
        chosen=st.multiselect('Choose 2–5 trials/programs',labels,max_selections=5,key='comp_trials')
        if chosen:
            ids=[x.split(' — ',1)[0] for x in chosen]; comp=land[land.nct_id.isin(ids)].copy(); matrix={'Attribute':['Sponsor','Intervention','Modality','Phase','Status','Enrollment','Primary completion']}
            for _,r in comp.iterrows(): matrix[r.nct_id]=[r.sponsor,r.interventions,r.modality,r.phases,r.status,r.enrollment,r.primary_completion_date]
            st.dataframe(pd.DataFrame(matrix),hide_index=True,width='stretch')
            st.markdown('##### Endpoint comparison')
            ce=eps[eps.nct_id.isin(ids)].copy()
            if not ce.empty:
                ce['endpoint']=ce.outcome_type+': '+ce.measure.fillna('')
                for nid in ids:
                    st.markdown(f'**{nid}**')
                    st.dataframe(ce[ce.nct_id==nid][['outcome_type','measure','time_frame','description']],hide_index=True,width='stretch')
with tab6:
    st.subheader('Trial explorer')
    st.caption('Search the complete ClinicalTrials.gov interventional trial universe for a disease, independent of the dashboard start-year selector.')
    disease_search=st.text_input('Disease / condition',placeholder='e.g., Huntington Disease, Alzheimer Disease, Ewing Sarcoma',key='explorer_disease')
    cfetch,cclear=st.columns([1,1])
    with cfetch:
        if st.button('Fetch all disease trials',type='primary',key='fetch_all_disease'):
            if not disease_search.strip():
                st.warning('Enter a disease or condition first.')
            else:
                try:
                    prog=st.progress(0,text='Querying ClinicalTrials.gov…')
                    rows,total=fetch_all_disease_trials(disease_search,prog)
                    prog.empty()
                    st.session_state['explorer_rows']=rows
                    st.session_state['explorer_query']=disease_search.strip()
                    st.session_state['explorer_total']=total
                except Exception as e:
                    st.error(f'Disease retrieval failed: {e}')
    with cclear:
        if st.button('Clear disease results',key='clear_disease_results'):
            for k in ['explorer_rows','explorer_query','explorer_total']:
                st.session_state.pop(k,None)

    rows=st.session_state.get('explorer_rows')
    if rows is not None:
        view=pd.DataFrame(rows)
        expected=st.session_state.get('explorer_total')
        query=st.session_state.get('explorer_query','')
        st.success(f"Retrieved {len(view):,}" + (f" of {expected:,}" if expected is not None else '') + f" interventional trials for {query} across all years and statuses.")
    else:
        view=f.copy()
        st.info('No full-disease search loaded yet. The table below is the current year-filtered dashboard dataset. Enter a disease above and click Fetch all disease trials for the complete disease universe.')

    if not view.empty:
        view=view.copy()
        view['therapeutic_area']=view.conditions.apply(classify_ta)
        view['modality']=view.apply(modality,axis=1)
        # Post-retrieval filters: these do not affect API completeness.
        fc1,fc2,fc3=st.columns(3)
        statuses=sorted([x for x in view.status.dropna().unique() if x])
        phases=sorted({x.strip() for v in view.phases.fillna('') for x in v.split(' | ') if x.strip()})
        sponsors=sorted([x for x in view.sponsor.dropna().unique() if x])
        with fc1: sel_status=st.multiselect('Status',statuses,key='explorer_status')
        with fc2: sel_phase=st.multiselect('Phase',phases,key='explorer_phase')
        with fc3: sel_sponsor=st.multiselect('Sponsor',sponsors,key='explorer_sponsor')
        if sel_status: view=view[view.status.isin(sel_status)]
        if sel_phase: view=view[view.phases.fillna('').apply(lambda x:any(p in [z.strip() for z in x.split(' | ')] for p in sel_phase))]
        if sel_sponsor: view=view[view.sponsor.isin(sel_sponsor)]
        keyword=st.text_input('Filter retrieved trials by NCT ID, title, sponsor, condition, intervention, or endpoint',key='explorer_keyword')
        if keyword:
            mask=pd.Series(False,index=view.index)
            for col in ['nct_id','title','sponsor','conditions','interventions','primary_outcomes']:
                mask|=view[col].fillna('').str.contains(keyword,case=False,regex=False)
            view=view[mask]
        st.caption(f'Showing {len(view):,} trials after filters.')
        view['Trial record']='https://clinicaltrials.gov/study/'+view.nct_id.fillna('')
        cols=['nct_id','title','sponsor','therapeutic_area','modality','phases','status','conditions','interventions','primary_outcomes','enrollment','start_date','primary_completion_date','countries','Trial record']
        st.dataframe(view[cols].sort_values('start_date',ascending=False),width='stretch',hide_index=True,column_config={'Trial record':st.column_config.LinkColumn('Trial',display_text='Open')})
    else:
        st.warning('No trials found for the current search/filters.')

with tab7:
    st.subheader('Individual Trial Intelligence')
    st.caption('Registry facts are shown separately from derived diligence prompts. Diligence prompts identify questions to investigate; they are not conclusions about trial quality, efficacy, or probability of success.')
    default_nct = f.iloc[0].nct_id if not f.empty else ''
    nct=st.text_input('NCT ID',value=default_nct,key='intel_nct')
    if st.button('Analyze trial',type='primary',key='analyze_trial'):
        try:
            st.session_state['trial_detail']=fetch_trial_detail(nct)
            st.session_state['trial_detail_nct']=nct.strip().upper()
        except Exception as e: st.error(f'Trial retrieval failed: {e}')
    study=st.session_state.get('trial_detail')
    if study and st.session_state.get('trial_detail_nct')==nct.strip().upper():
        ti=trial_intelligence(study)
        st.markdown(f"### {ti['title'] or ti['nct_id']}")
        st.caption(f"{ti['nct_id']} · {ti['sponsor'] or 'Sponsor not reported'} · {ti['phase'] or 'Phase not reported'}")
        c1,c2,c3,c4=st.columns(4); c1.metric('Status',ti['status'] or '—'); c2.metric('Enrollment',ti['enrollment'] if ti['enrollment'] is not None else '—'); c3.metric('Arms',ti['arms']); c4.metric('Primary endpoints',len(ti['primary']))
        st.markdown('#### Registry facts')
        a,b=st.columns(2)
        with a:
            st.markdown('**Design**')
            st.dataframe(pd.DataFrame({'Field':['Allocation','Intervention model','Masking','Primary purpose','Enrollment type'],'Registered value':[ti['allocation'],ti['intervention_model'],ti['masking'],ti['primary_purpose'],ti['enrollment_type'] or 'Not reported']}),hide_index=True,width='stretch')
        with b:
            st.markdown('**Population**')
            st.dataframe(pd.DataFrame({'Field':['Conditions','Sex','Minimum age','Maximum age','Healthy volunteers'],'Registered value':[ti['conditions'],ti['sex'],ti['minimum_age'],ti['maximum_age'],str(ti['healthy_volunteers']) if ti['healthy_volunteers'] is not None else 'Not reported']}),hide_index=True,width='stretch')
        st.markdown('#### Endpoint intelligence')
        for label,key in [('Primary endpoints','primary'),('Secondary endpoints','secondary')]:
            st.markdown(f'**{label}**')
            oo=ti[key]
            if oo: st.dataframe(pd.DataFrame([{'Measure':o.get('measure',''),'Time frame':o.get('timeFrame',''),'Description':o.get('description','')} for o in oo]),hide_index=True,width='stretch')
            else: st.info(f'No {label.lower()} registered.')
        st.markdown('#### Diligence prompts · derived analysis')
        if ti['flags']:
            for title,desc in ti['flags']: st.warning(f'**{title}** — {desc}')
        else: st.info('No rule-based diligence prompts were triggered by the currently registered fields. This does not mean the trial has no analytical risks.')
        st.markdown('#### Eligibility criteria')
        with st.expander('View registered inclusion / exclusion criteria'):
            st.text(ti['criteria'])
        st.markdown('#### Results intelligence')
        ri=results_intelligence(study)
        if not ri['has_results']:
            st.info('No structured results are posted in this ClinicalTrials.gov record. V0.5C will add publications, company disclosures and external-control sources so analysis is not limited to registry-posted results.')
        else:
            st.success('Structured results are available for this study.')
            ctype,cqs=comparator_intelligence(ti,ri)
            c1,c2,c3,c4=st.columns(4)
            c1.metric('Result groups',len(ri['groups']))
            c2.metric('Outcome result rows',len(ri['outcomes']))
            c3.metric('Statistical analyses',len(ri['analyses']))
            c4.metric('AE rows',len(ri['adverse_events']))
            st.markdown('**Comparator classification · derived**')
            st.info(ctype)
            for q in cqs: st.warning(q)
            st.markdown('**Reported outcome measurements**')
            if not ri['outcomes'].empty:
                types=['PRIMARY','SECONDARY','OTHER_PRE_SPECIFIED','POST_HOC']
                present=[x for x in types if x in set(ri['outcomes']['Outcome type'].astype(str))]
                pick=st.multiselect('Outcome types to show',present,default=present,key='result_outcome_types') if present else []
                rv=ri['outcomes'] if not pick else ri['outcomes'][ri['outcomes']['Outcome type'].isin(pick)]
                st.dataframe(rv,hide_index=True,width='stretch')
            else: st.info('The results section exists, but no structured outcome measurement rows were parsed.')
            st.markdown('**Reported statistical analyses**')
            if not ri['analyses'].empty: st.dataframe(ri['analyses'],hide_index=True,width='stretch')
            else: st.info('No structured statistical-analysis records were found for the reported outcomes.')
            st.markdown('**Safety / adverse events**')
            if not ri['adverse_events'].empty:
                sev=st.selectbox('Adverse-event view',['Serious','Other','All'],key='ae_view')
                av=ri['adverse_events'] if sev=='All' else ri['adverse_events'][ri['adverse_events']['Type']==sev]
                st.dataframe(av,hide_index=True,width='stretch')
            else: st.info('No structured adverse-event rows were parsed from this record.')
            st.markdown('#### Registry vs results audit')
            actual=ti['enrollment']
            flow_groups=len(ri['groups'])
            primary_registered=len(ti['primary']); secondary_registered=len(ti['secondary'])
            result_types=set(ri['outcomes']['Outcome type'].astype(str)) if not ri['outcomes'].empty else set()
            audit=pd.DataFrame([
                {'Question':'Enrollment recorded','Registry / result signal':actual if actual is not None else 'Not reported','Diligence use':'Compare planned vs actual enrollment using historical snapshots and publications.'},
                {'Question':'Result groups represented','Registry / result signal':flow_groups,'Diligence use':'Check whether all randomized/treated arms contribute to reported results.'},
                {'Question':'Registered primary endpoints','Registry / result signal':primary_registered,'Diligence use':'Check whether each prespecified primary endpoint has a corresponding reported result.'},
                {'Question':'Primary results present','Registry / result signal':'Yes' if 'PRIMARY' in result_types else 'No / not parsed','Diligence use':'Investigate missing or differently labeled primary results.'},
                {'Question':'Registered secondary endpoints','Registry / result signal':secondary_registered,'Diligence use':'Compare prespecified secondary outcomes with what is emphasized publicly.'},
                {'Question':'Secondary results present','Registry / result signal':'Yes' if 'SECONDARY' in result_types else 'No / not parsed','Diligence use':'Look for selective reporting, timing differences, or incomplete posting.'}
            ])
            st.dataframe(audit,hide_index=True,width='stretch')
            st.caption('Treatment-effect calculations are shown only when ClinicalTrials.gov supplies an explicit structured statistical analysis or sufficiently comparable arm-level values. V0.5B does not infer missing statistics.')
        st.markdown(f"[Open {ti['nct_id']} on ClinicalTrials.gov](https://clinicaltrials.gov/study/{ti['nct_id']})")
    else:
        st.info('Enter an NCT ID and click “Analyze trial.” This fetches the current full study record so design and eligibility fields are not limited by the year-level dataset.')

with tab8:
    st.subheader('Evidence Intelligence')
    st.caption('Build a provenance-aware evidence package around an NCT ID and follow how the disclosed dataset evolves over time.')
    evidence_nct=st.text_input('NCT ID for evidence package',value=st.session_state.get('trial_detail_nct',''),key='evidence_nct').strip().upper()
    st.markdown('#### Evidence Discovery')
    st.caption('Searches the ClinicalTrials.gov record and PubMed for trial-linked evidence. Candidates are not saved until you review and select them.')
    if st.button('Discover evidence automatically',type='primary',disabled=not bool(evidence_nct)):
        with st.spinner('Searching ClinicalTrials.gov and PubMed…'):
            found,errs,diag=discover_evidence(evidence_nct)
            st.session_state['discovery_nct']=evidence_nct; st.session_state['discovered_evidence']=found; st.session_state['discovery_errors']=errs; st.session_state['discovery_diagnostics']=diag
    if st.session_state.get('discovery_nct')==evidence_nct and 'discovered_evidence' in st.session_state:
        candidates=st.session_state.get('discovered_evidence',[])
        for msg in st.session_state.get('discovery_diagnostics',[]): st.caption(msg)
        for err in st.session_state.get('discovery_errors',[]): st.warning(err)
        if not candidates: st.info('No directly linked ClinicalTrials.gov references/documents or PubMed records were found for this NCT ID. You can still add company disclosures manually below.')
        else:
            st.success(f'Found {len(candidates)} candidate evidence sources. Review before saving.')
            for i,r in enumerate(candidates):
                with st.container(border=True):
                    a,b=st.columns([5,1])
                    with a:
                        st.markdown(f"**{r.get('source_title') or 'Untitled source'}**")
                        st.caption(f"{r.get('source_type')} · {r.get('provenance')} · {r.get('source_date') or 'date not parsed'}")
                        if r.get('result_notes'): st.write(r.get('result_notes'))
                        if r.get('source_url'): st.markdown(f"[Open source]({r.get('source_url')})")
                    with b:
                        if st.button('Save',key=f"save_disc_{evidence_nct}_{i}"):
                            save_discovered_evidence(evidence_nct,r); st.success('Saved to evidence package.')
    st.markdown('#### Manual evidence entry')
    with st.expander('Add evidence record',expanded=True):
        e1,e2=st.columns(2)
        with e1:
            source_type=st.selectbox('Source type',['Publication','Conference abstract','Company presentation','Press release','Regulatory document','Natural-history dataset','Other'])
            source_title=st.text_input('Source title / description')
            source_date=st.text_input('Source/publication date (YYYY-MM-DD)')
            data_cut_date=st.text_input('Data-cut date (YYYY-MM-DD, if known)')
            source_url=st.text_input('Source URL / reference')
            reported_n=st.text_input('Reported N')
        with e2:
            follow_up=st.text_input('Follow-up (e.g., 24 months)')
            endpoints_emphasized=st.text_area('Endpoints emphasized')
            comparator=st.text_input('Comparator / external control')
            result_notes=st.text_area('Reported result notes')
            analyst_notes=st.text_area('Analyst notes / questions')
        if st.button('Save evidence record',type='primary'):
            if not evidence_nct: st.error('Enter an NCT ID first.')
            elif not source_title.strip(): st.error('Add a source title or description.')
            else:
                save_evidence({'nct_id':evidence_nct,'source_type':source_type,'source_title':source_title,'source_date':source_date,'data_cut_date':data_cut_date,'source_url':source_url,'reported_n':reported_n,'follow_up':follow_up,'endpoints_emphasized':endpoints_emphasized,'comparator':comparator,'result_notes':result_notes,'analyst_notes':analyst_notes})
                st.success('Evidence record saved locally.')
    if evidence_nct:
        ev=load_evidence(evidence_nct)
        st.markdown('#### Evidence package')
        if ev.empty: st.info('No evidence records saved for this NCT ID yet.')
        else:
            c1,c2,c3=st.columns(3); c1.metric('Evidence records',len(ev)); c2.metric('Source types',ev['source_type'].nunique()); c3.metric('Data cuts recorded',ev['data_cut_date'].replace('',pd.NA).dropna().nunique())
            st.dataframe(ev[['source_type','source_title','source_date','data_cut_date','reported_n','follow_up','endpoints_emphasized','comparator','result_notes','analyst_notes','source_url']],hide_index=True,width='stretch',column_config={'source_url':st.column_config.LinkColumn('Source')})
            st.markdown('#### Data-cut history')
            st.dataframe(ev[['data_cut_date','source_date','source_type','source_title','reported_n','follow_up','endpoints_emphasized','comparator']],hide_index=True,width='stretch')
            prompts=evidence_change_prompts(ev)
            st.markdown('#### Longitudinal diligence prompts · derived')
            if prompts:
                for period,field,oldv,newv in prompts: st.warning(f'**{period} · {field} changed** — {oldv} → {newv}. Check whether this reflects maturing follow-up, a different analysis population, a revised comparator, or a shift in disclosure emphasis.')
            else: st.info('No comparable successive records yet, or no tracked fields changed between them.')
            st.caption('A change between disclosures is a diligence signal, not evidence of a problem by itself. Review the underlying source and analysis population before drawing conclusions.')
    else: st.info('Enter an NCT ID to create or review its evidence package.')

st.caption('Sources: ClinicalTrials.gov API v2, PubMed/NCBI E-utilities, plus user-curated external evidence records. V0.5C.2 adds resilient multi-source evidence discovery while preserving provenance-aware evidence packages and longitudinal data-cut history. External evidence is stored locally and is not automatically verified; derived prompts are questions for diligence, not conclusions about efficacy or trial quality.')
