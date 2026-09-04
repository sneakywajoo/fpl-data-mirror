import json, math, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

FPL='https://fantasy.premierleague.com/api'
LEAGUE=int(os.environ.get('FPL_LEAGUE','351382'))
OWN=int(os.environ.get('FPL_ENTRY','4765608'))
UA='fpl-github-mirror/1.0'

def get(path, allow404=False):
    req=Request(FPL+path,headers={'User-Agent':UA,'Accept':'application/json'})
    try:
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        if allow404 and e.code in (404,403): return None
        raise

def all_standings():
    out=[]; page=1; league=None
    while page<=50:
        d=get(f'/leagues-classic/{LEAGUE}/standings/?page_standings={page}')
        league=league or d.get('league')
        s=d.get('standings',{})
        out.extend(s.get('results',[]))
        if not s.get('has_next'): break
        page+=1
    return league,out

def historical_score(h):
    past=h.get('past') or []
    if not past: return None
    score=weight=0.0
    for i,s in enumerate(reversed(past)):
        w=1/(1+i*.25)
        rank=max(1,int(s.get('rank') or s.get('overall_rank') or 10_000_000))
        score += w*math.log10(rank); weight += w
    return score/weight if weight else None

def newest_public_gw(bootstrap):
    current=next((e for e in bootstrap.get('events',[]) if e.get('is_current')),None)
    nxt=next((e for e in bootstrap.get('events',[]) if e.get('is_next')),None)
    finished=next((e for e in reversed(bootstrap.get('events',[])) if e.get('finished')),None)
    candidates=[]
    for e in (nxt,current,finished):
        if e and e.get('id') not in candidates: candidates.append(e['id'])
    candidates=sorted(candidates, reverse=True)
    for gw in candidates:
        p=get(f'/entry/{OWN}/event/{gw}/picks/', allow404=True)
        if p is not None:
            return gw,p,'highest_public_picks'
    gw=(finished or current or {'id':1})['id']
    return gw,None,'fallback'

def fetch_manager(row, gw, history, own_picks=None):
    eid=int(row['entry'])
    entry=get(f'/entry/{eid}/')
    picks=own_picks if eid==OWN and own_picks is not None else get(f'/entry/{eid}/event/{gw}/picks/', allow404=True)
    transfers=get(f'/entry/{eid}/transfers/', allow404=True) or []
    return {
        'entry':eid,'rank':row.get('rank'),'last_rank':row.get('last_rank'),'total':row.get('total'),
        'entry_name':row.get('entry_name'),'player_name':row.get('player_name'),
        'manager':{
            'name':f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(),
            'team_name':entry.get('name'),'started_event':entry.get('started_event'),
            'favourite_team':entry.get('favourite_team'),'last_deadline_value':entry.get('last_deadline_value'),
            'last_deadline_bank':entry.get('last_deadline_bank'),
            'last_deadline_total_transfers':entry.get('last_deadline_total_transfers')
        },
        'historical_strength':historical_score(history),
        'history':{'current':history.get('current',[]),'past':history.get('past',[]),'chips':history.get('chips',[])},
        'picks': None if picks is None else {
            'active_chip':picks.get('active_chip'),'automatic_subs':picks.get('automatic_subs',[]),
            'entry_history':picks.get('entry_history'),'picks':picks.get('picks',[])
        },
        'recent_transfers':[t for t in transfers if int(t.get('event',0))<=gw][:30]
    }

def main():
    bootstrap=get('/bootstrap-static/')
    league, standings=all_standings()
    gw, own_picks, gw_source=newest_public_gw(bootstrap)

    histories={}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs={ex.submit(get,f"/entry/{int(r['entry'])}/history/"):int(r['entry']) for r in standings}
        for fut,eid in [(f,e) for f,e in futs.items()]:
            try: histories[eid]=fut.result()
            except Exception as exc: histories[eid]={'current':[],'past':[],'chips':[],'error':str(exc)}

    managers=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs={ex.submit(fetch_manager,r,gw,histories.get(int(r['entry']),{}),own_picks):r for r in standings}
        for fut in as_completed(futs):
            try: managers.append(fut.result())
            except Exception as exc:
                r=futs[fut]; managers.append({'entry':int(r['entry']),'error':str(exc)})
    rankpos={int(r['entry']):i for i,r in enumerate(standings)}
    managers.sort(key=lambda m:rankpos.get(int(m.get('entry',0)),999999))

    hist_ranked=sorted(
        [m for m in managers if m.get('historical_strength') is not None],
        key=lambda m:m['historical_strength']
    )
    elements={str(p['id']):{'id':p['id'],'name':p['web_name'],'team':p['team'],'position':p['element_type'],'price':p['now_cost'],'status':p['status'],'chance_next':p.get('chance_of_playing_next_round')} for p in bootstrap.get('elements',[])}
    teams={str(t['id']):{'id':t['id'],'name':t['name'],'short_name':t['short_name']} for t in bootstrap.get('teams',[])}
    own_standing=next((r for r in standings if int(r['entry'])==OWN),None)
    events=bootstrap.get('events',[])
    payload={
        'ok':True,'source':'github-actions-direct-fpl','generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'query':{'league':LEAGUE,'entry':OWN,'gw':gw},'gw_resolution':{'gw':gw,'source':gw_source,'public':own_picks is not None},
        'events':{
            'current':next((e for e in events if e.get('is_current')),None),
            'next':next((e for e in events if e.get('is_next')),None),
            'latest_finished':next((e for e in reversed(events) if e.get('finished')),None)
        },
        'league':league,'own_standing':own_standing,'standings':standings,'league_manager_count':len(standings),
        'historically_strongest_in_league':[{
            'entry':m['entry'],'player_name':m.get('player_name'),'team_name':m.get('entry_name'),
            'current_rank':m.get('rank'),'current_total':m.get('total'),'historical_strength':m.get('historical_strength'),
            'past_seasons':m.get('history',{}).get('past',[])
        } for m in hist_ranked[:20]],
        'managers':managers,'lookup':{'elements':elements,'teams':teams},
        'notes':['All manager lineups are only included once the FPL picks endpoint makes that Gameweek public.','Unrevealed pre-deadline transfers are not available.']
    }
    os.makedirs('snapshot',exist_ok=True)
    with open('snapshot/fpl.json','w') as f: json.dump(payload,f,separators=(',',':'))
    print(f"ok gw={gw} managers={len(managers)} own_rank={own_standing.get('rank') if own_standing else None}")

if __name__=='__main__': main()
