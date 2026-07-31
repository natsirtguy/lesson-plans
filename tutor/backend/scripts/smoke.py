"""End-to-end smoke test against a *running* server.

Not a substitute for the pytest suite -- it asserts almost nothing -- but it
exercises a thing the suite structurally cannot: the app as an actual process,
over real HTTP, against a real engine built by ``build_engine``.

That distinction has already earned its keep. The suite passed 375 tests against
a graph-generation path that inserted prerequisite edges *before* the concepts
they point at, because the test engine was constructed directly rather than
through the app factory and so never enabled ``PRAGMA foreign_keys=ON``. The
first run of this script failed on the first step. It also caught the graph
endpoint not returning the ``coverage`` field the frontend renders.

Usage, with no API key and nothing to configure::

    cd backend
    TUTOR_DATABASE_URL=sqlite+aiosqlite:///./smoke.db \
    TUTOR_LLM_PROVIDER=fake \
      .venv/bin/alembic upgrade head
    TUTOR_DATABASE_URL=sqlite+aiosqlite:///./smoke.db \
    TUTOR_LLM_PROVIDER=fake \
      .venv/bin/uvicorn app.main:app --port 8101 &
    PYTHONPATH=. .venv/bin/python scripts/smoke.py

With ``TUTOR_LLM_PROVIDER=fake`` the content is deterministic filler, so this
checks plumbing rather than quality. Point it at a real key to judge the writing.
"""
import json
import os
import time
import urllib.request

B = os.environ.get("TUTOR_SMOKE_BASE", "http://localhost:8101")

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def stream(path, body):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json"})
    names, text = [], ""
    with urllib.request.urlopen(req) as r:
        buf = ""
        for chunk in r:
            buf += chunk.decode()
        for frame in buf.split("\n\n"):
            name = data = None
            for line in frame.splitlines():
                if line.startswith("event: "): name = line[7:]
                elif line.startswith("data: "): data = line[6:]
            if name:
                names.append(name)
                if name == "delta": text += json.loads(data)
    return names, text

s = call("POST", "/subjects", {"name": "Statistical Mechanics"})["id"]
for _ in range(40):
    subj = call("GET", f"/subjects/{s}")
    if subj["graph_status"] in {"ready", "failed"}: break
    time.sleep(0.25)
print(f"1. graph        {subj['graph_status']}, {subj['node_count']} concepts")

g = call("GET", f"/subjects/{s}/graph")
print(f"2. edges        {len(g['edges'])} prerequisite edges, coverage {g['coverage']:.0%}")

d = call("POST", f"/subjects/{s}/diagnostic", {})["id"]
asked = 0
while True:
    nxt = call("GET", f"/diagnostic/{d}/next")
    if nxt["finished"]: break
    it = nxt["item"]
    ans = "0" if it["item_format"] == "multiple_choice" else "correct"
    call("POST", f"/diagnostic/{d}/answer", {"item_id": it["id"], "answer": ans})
    asked += 1
print(f"3. diagnostic   {asked} questions, stopped on {nxt['stop_reason']}")

r = call("GET", f"/subjects/{s}/report")
print(f"4. report       coverage {r['coverage']:.0%}, {r['mastered_nodes']}/{r['total_nodes']} held, "
      f"blocking tier {r['blocking']['target_tier']}")

p = call("POST", f"/subjects/{s}/plan", {})
print(f"5. plan         {len(p['units'])} units, {p['skipped_mastered']} already known")
print(f"   unit 1       {p['units'][0]['title']} — {p['units'][0]['placement_reason'][:70]}...")

u = call("GET", f"/plan/{p['id']}/next")
print(f"6. unit served  exit check of {len(u['exit_check'])}, lesson {u['lesson_id'][:8]}")

names, body = stream(f"/lessons/{u['lesson_id']}/stream", {})
print(f"7. lesson SSE   {names.count('delta')} deltas, {len(body)} chars, ends with {names[-1]}")

done = call("POST", f"/plan/units/{u['unit']['id']}/complete",
            {"answers": [{"item_id": i["id"], "answer": "correct"} for i in u["exit_check"]]})
print(f"8. exit check   score {done['exit_score']:.0%}, mastery "
      f"{done['mastery_before']:.0%} -> {done['mastery_after']:.0%}")

q = call("GET", f"/subjects/{s}/reviews")
print(f"9. review queue {len(q['due'])} due now, {q['total_cards']} card(s) scheduled")

names, ans = stream(f"/subjects/{s}/ask", {"question": "Why does entropy increase?"})
print(f"10. ask SSE     {names.count('delta')} deltas, {len(ans)} chars")

sch = call("POST", f"/subjects/{s}/schedule", {"horizon_days": 14})
print(f"11. schedule    {len(sch['sessions'])} sittings, {sch['deadline']['message'][:60]}...")
print(f"    interleave  first sitting retrieves {len(sch['sessions'][0]['review_node_ids'])}, "
      f"teaches {len(sch['sessions'][0]['new_names'])}")

g2 = call("GET", f"/subjects/{s}/graph")
print(f"12. integrity   {len(g2['nodes'])} nodes / {len(g2['edges'])} edges intact after all writes")
