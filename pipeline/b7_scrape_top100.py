"""B7 (D8, Q6, C12): scrape MLB Pipeline preseason Top 100 (2014-2020) to raw JSON: `python -m pipeline.b7_scrape_top100 OUT.json [YEAR ...]`,
then `python -m pipeline.b7_top100 OUT.json` (replaces only the scraped list years in data/manual/top100.csv).
The committed data/manual/top100.csv is the artifact; this is provenance only (names get leading '. ' stripped by hand: 2016 #100 rendered '100 . Matt Olson')."""
import re,subprocess,csv,json,sys
U={2014:"2014-top-100-mlb-prospects-list-c301609478",2015:"2015-top-100-mlb-prospects-list-c301609384",2016:"2016-top-100-mlb-prospects-list-c301608606",2017:"2017-top-100-mlb-prospects-list-c301608460",2018:"2018-top-100-mlb-prospects-list-c301606192",
   2019:"2019-top-100-mlb-prospects-list",2020:"2020-top-100-mlb-prospects-list"}  # 2019-20: C12 fresh holdout (v1.1)
OUT=sys.argv[1] if len(sys.argv)>1 else '/tmp/raw100.json'
YEARS=[int(y) for y in sys.argv[2:]] or list(U)
POS=re.compile(r'^(C|1B|2B|3B|SS|LF|CF|RF|OF|DH|INF|IF|RHP|LHP|P|SP|RP)(/(C|1B|2B|3B|SS|LF|CF|RF|OF|DH|INF|IF|RHP|LHP))*$')
rows=[]
for y,s in ((y,U[y]) for y in YEARS):
    url="https://www.mlb.com/news/"+s
    t=subprocess.run(["curl","-sL","-A","Mozilla/5.0 (Macintosh) Safari/605",url],capture_output=True,text=True).stdout
    cs=re.findall(r'"content":"((?:[^"\\]|\\.)*)"',t)
    txt="\n".join(json.loads('"'+c+'"') for c in cs)
    got={}
    for l in txt.split('\n'):
        m=re.match(r'\s*(\d{1,3})\s*(?:\\?\.|\))\s+(.*)',l)  # "12." (2014-19) or "12)" (2020)
        if not m: continue
        r=int(m.group(1)); b=m.group(2)
        b=re.sub(r'\[\]\([^)]*\)','',b); b=re.sub(r'<[^>]+>','',b)
        b=re.sub(r'\[([^\]]*)\]\([^)]*\)',r'\1',b); b=b.replace('**','').strip()
        tk=[x.strip() for x in b.split(',')]
        if len(tk)==2 and ' ' in tk[1]:
            a,c=tk[1].rsplit(' ',1); tk=[tk[0],a,c]
        if len(tk)!=3: print('BAD',y,r,tk); continue
        n,p,o=tk
        if not POS.match(p) and POS.match(o): p,o=o,p
        if not POS.match(p): print('POS?',y,r,tk)
        if r in got: r+=1  # source typo: duplicate rank number, next entry is the following rank
        got[r]=(n,p,o)
    print(y,len(got),sorted(set(range(1,101))-set(got)))
    for r,(n,p,o) in sorted(got.items()): rows.append(dict(list_year=y,source='pipeline',source_url=url,rank=r,name=n,pos=p,org=o))
json.dump(rows,open(OUT,'w'))
