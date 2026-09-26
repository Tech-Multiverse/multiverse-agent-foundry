import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from src.a2a.client import send_json_message
from src.config_schema import TaskConfig
from src.settings import FoundrySettings
from src.telemetry import new_trace_id
from src.zoo.storage import ZooStore


settings = FoundrySettings()
data_dir = settings.foundry_data_dir
if data_dir == Path("/app/data") and not Path("/app").exists():
    data_dir = Path("data")
data_dir.mkdir(parents=True, exist_ok=True)
store = ZooStore(data_dir / "zoo.sqlite")
app = FastAPI(title="Multiverse Foundry Agent Zoo")


async def execute_run(thread_id: str, trace_id: str, task: dict[str, Any]) -> None:
    try:
        store.add_event(thread_id, trace_id, "a2a.builder.requested", "Dashboard", "Task sent to Builder over A2A", "Builder")
        result = await send_json_message(
            str(settings.builder_a2a_url).rstrip("/"),
            {"task": task, "thread_id": thread_id, "trace_id": trace_id},
        )
        status = result.get("status", "completed")
        store.set_run_status(thread_id, status, result)
        store.add_event(thread_id, trace_id, f"run.{status}", "System", f"Run {status}")
    except Exception as error:
        store.set_run_status(thread_id, "failed", {"error": f"{type(error).__name__}: {error}"})
        store.add_event(thread_id, trace_id, "run.failed", "System", f"Run failed: {type(error).__name__}")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return _DASHBOARD_HTML


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    return store.list_runs()


@app.get("/api/runs/{thread_id}")
def get_run(thread_id: str) -> dict[str, Any]:
    run = store.get_run(thread_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/api/runs", status_code=202)
def create_run(task: TaskConfig, background_tasks: BackgroundTasks) -> dict[str, str]:
    thread_id = uuid4().hex
    trace_id = new_trace_id()
    payload = task.model_dump(mode="json")
    store.create_run(thread_id, trace_id, payload)
    store.add_event(thread_id, trace_id, "run.queued", "Dashboard", "Expedition queued")
    background_tasks.add_task(execute_run, thread_id, trace_id, payload)
    return {"thread_id": thread_id, "trace_id": trace_id, "status": "queued"}


@app.post("/api/runs/{thread_id}/resume/{action}", status_code=202)
def resume_run(thread_id: str, action: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    if action not in {"retry", "continue_without_tool", "cancel"}:
        raise HTTPException(status_code=400, detail="Invalid resume action")
    run = store.get_run(thread_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def resume() -> None:
        try:
            result = await send_json_message(
                str(settings.runner_a2a_url).rstrip("/"),
                {"thread_id": thread_id, "trace_id": run["trace_id"], "resume": action},
            )
            store.set_run_status(thread_id, result.get("status", "completed"), result)
        except Exception as error:
            store.set_run_status(thread_id, "failed", {"error": f"{type(error).__name__}: {error}"})

    store.set_run_status(thread_id, "running")
    background_tasks.add_task(resume)
    return {"thread_id": thread_id, "status": "running"}


@app.get("/api/events/latest")
def latest_event() -> dict[str, int]:
    return {"sequence": store.latest_event_sequence()}


@app.get("/events")
async def events(after: int = 0, thread_id: str | None = None) -> StreamingResponse:
    async def stream():
        cursor = after
        idle_ticks = 0
        while True:
            rows = store.list_events(after=cursor, thread_id=thread_id)
            if rows:
                for row in rows:
                    cursor = row["sequence"]
                    yield f"id: {cursor}\ndata: {json.dumps(row, separators=(',', ':'))}\n\n"
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks >= 15:
                    yield ": keepalive\n\n"
                    idle_ticks = 0
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


_DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multiverse Foundry Agent Zoo</title>
<style>
:root{--bg:#07111f;--panel:#0d1b2d;--line:#223654;--text:#e8f0ff;--muted:#8fa6c5;--cyan:#55d6d0;--gold:#ffc857;--green:#62d394;--red:#ff6b6b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#102846,var(--bg) 45%);color:var(--text);font:15px Inter,ui-sans-serif,system-ui;min-height:100vh}header{padding:28px 34px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}h1{margin:0;font-size:28px;letter-spacing:.03em}h1 span{color:var(--cyan)}main{display:grid;grid-template-columns:340px 1fr;gap:22px;padding:22px;max-width:1500px;margin:auto}.panel{background:rgba(13,27,45,.94);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 18px 50px #0005}label{display:block;color:var(--muted);margin:12px 0 6px}input,textarea,select,button{width:100%;background:#081525;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px;font:inherit}textarea{min-height:95px;resize:vertical}button{margin-top:14px;background:linear-gradient(135deg,#167d86,#2456a6);border:0;font-weight:700;cursor:pointer}button:hover{filter:brightness(1.15)}.run{padding:14px;border:1px solid var(--line);border-radius:10px;margin:10px 0;cursor:pointer;background:#091827}.run:hover{border-color:var(--cyan)}.status{display:inline-block;padding:4px 8px;border-radius:99px;background:#263b57;color:var(--gold);font-size:12px}.status.completed{color:var(--green)}.status.failed{color:var(--red)}.agents{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.agent{border:1px solid var(--line);border-top:3px solid var(--cyan);border-radius:10px;padding:14px;background:#091827;cursor:pointer;transition:.2s}.agent:hover{transform:translateY(-2px);box-shadow:0 8px 25px #0006;border-color:var(--cyan)}.agent h3{margin:0 0 8px}.tools{color:var(--muted);font-size:12px}.board{margin-top:18px}.message{display:grid;grid-template-columns:130px 1fr;gap:12px;padding:12px 0;border-bottom:1px solid var(--line)}.who{color:var(--cyan);font-weight:700}.type{font-size:11px;color:var(--gold);text-transform:uppercase}.content{white-space:pre-wrap;line-height:1.45}.empty{color:var(--muted);padding:30px;text-align:center}.flow{color:var(--muted);font-family:ui-monospace,monospace;margin-bottom:14px}.result{white-space:pre-wrap;background:#081525;padding:12px;border-radius:8px;max-height:260px;overflow:auto}.pipeline{display:flex;gap:6px;align-items:center;overflow:auto;padding:12px 0}.node{padding:8px 12px;border:1px solid var(--line);border-radius:99px;white-space:nowrap}.node.active{border-color:var(--cyan);box-shadow:0 0 18px #55d6d066;animation:pulse 1.2s infinite}.arrow{color:var(--muted)}.timeline{max-height:300px;overflow:auto;background:#081525;border-radius:10px;padding:8px}.event{display:grid;grid-template-columns:72px 130px 1fr;gap:10px;padding:8px;border-bottom:1px solid #182a43}.event-type{color:var(--gold);font-size:11px}.drawer{position:fixed;right:-520px;top:0;width:min(500px,92vw);height:100vh;background:#091827;border-left:1px solid var(--cyan);z-index:20;padding:24px;overflow:auto;transition:right .25s;box-shadow:-20px 0 50px #0009}.drawer.open{right:0}.close{width:auto;float:right;margin:0;background:#263b57}.detail-block{background:#07111f;border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0;white-space:pre-wrap}.live-dot{display:inline-block;width:8px;height:8px;background:var(--green);border-radius:50%;margin-right:6px;animation:pulse 1.2s infinite}@keyframes pulse{50%{opacity:.35;transform:scale(.8)}}@media(max-width:850px){main{grid-template-columns:1fr}header{padding:20px}}
</style></head><body><header><h1>Multiverse Foundry <span>Agent Zoo</span></h1><div class="status" id="connection">connecting</div></header><main><aside><section class="panel"><h2>Launch expedition</h2><form id="task-form"><label>Topic</label><textarea id="topic">How serialized multi-agent systems make local AI practical on an 8GB GPU</textarea><label>Maximum agents</label><select id="max-agents"><option>2</option><option selected>3</option><option>4</option></select><label>Tools</label><select id="tools" multiple><option selected>web_search</option><option>file_write</option><option>calculator</option></select><button>Release the agents</button></form></section><section class="panel" style="margin-top:18px"><h2>Expeditions</h2><div id="runs"></div></section></aside><section class="panel"><div class="flow">Task → Builder A2A → Runner A2A → Agents → MCP → Message Board</div><div id="detail" class="empty">Select or launch an expedition to watch the zoo.</div></section></main><aside id="agent-drawer" class="drawer"><button class="close" onclick="closeAgent()">Close</button><div id="agent-detail"></div></aside>
<script>
const $=id=>document.getElementById(id);let selected=null,currentRun=null,lastEvent=0;const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(url,options){const response=await fetch(url,options);const text=await response.text();if(!response.ok)throw new Error(text||`HTTP ${response.status}`);return text?JSON.parse(text):null}
async function loadRuns(){const runs=await api('/api/runs');$('runs').innerHTML=runs.map(r=>`<div class="run" data-id="${esc(r.thread_id)}"><b>${esc(r.task?.task_input?.topic||r.thread_id)}</b><br><span class="status ${esc(r.status)}">${esc(r.status)}</span></div>`).join('')||'<div class="empty">No expeditions yet.</div>';document.querySelectorAll('.run').forEach(x=>x.onclick=()=>showRun(x.dataset.id));if(selected)showRun(selected)}
async function showRun(id){selected=id;const r=await api('/api/runs/'+id);currentRun=r;const agents=(r.agents||[]).map(a=>`<div class="agent" onclick="openAgent('${encodeURIComponent(a.role)}')"><h3>${esc(a.role)}</h3><span class="status ${esc(a.status)}">${esc(a.status)}</span><div class="tools">Tools: ${esc((a.tool_allowlist||[]).join(', ')||'none')}</div><small>Click for details</small></div>`).join('');const messages=(r.messages||[]).map(m=>`<div class="message"><div><div class="who">${esc(m.from_agent)}</div><div>→ ${esc(m.to_agent)}</div><div class="type">${esc(m.message_type)} · round ${esc(m.round)}</div></div><div class="content">${esc(m.content)}</div></div>`).join('');const events=(r.events||[]).slice(-80).map(e=>`<div class="event"><span>${esc(new Date(e.created_at).toLocaleTimeString())}</span><span class="event-type">${esc(e.event_type)}</span><span><b>${esc(e.actor)}</b> ${esc(e.summary)}</span></div>`).join('');const latest=(r.events||[]).at(-1)?.event_type||'';const active=n=>latest.startsWith(n)?'active':'';const pipeline=`<div class="pipeline"><span class="node ${active('builder')}">Builder</span><span class="arrow">→</span><span class="node ${active('a2a')}">A2A</span><span class="arrow">→</span><span class="node ${active('runner')}">Runner</span><span class="arrow">→</span><span class="node ${active('agent')}">Agents</span><span class="arrow">→</span><span class="node ${active('mcp')}">MCP</span><span class="arrow">→</span><span class="node ${active('zoo')}">Board</span></div>`;const result=r.result?`<h2>Result</h2><div class="result">${esc(JSON.stringify(r.result,null,2))}</div>`:'';const controls=r.status==='paused'?`<h2>Resource decision</h2><button onclick="resumeRun('${esc(id)}','retry')">Retry after adding tool</button><button onclick="resumeRun('${esc(id)}','continue_without_tool')">Continue without tool</button><button onclick="resumeRun('${esc(id)}','cancel')">Cancel</button>`:'';$('detail').innerHTML=`<h2>${r.status==='running'?'<span class="live-dot"></span>':''}${esc(r.task?.task_input?.topic||id)}</h2><p>Thread: ${esc(id)} · Trace: ${esc(r.trace_id)}</p>${pipeline}<h2>Agents</h2><div class="agents">${agents||'<div class="empty">Builder is designing the crew.</div>'}</div><h2>Live activity</h2><div class="timeline" id="timeline">${events||'<div class="empty">Waiting for the first event.</div>'}</div><div class="board"><h2>Message board</h2>${messages||'<div class="empty">Agents have not posted yet.</div>'}</div>${controls}${result}`;const t=$('timeline');if(t)t.scrollTop=t.scrollHeight}
function openAgent(encoded){const role=decodeURIComponent(encoded),a=(currentRun?.agents||[]).find(x=>x.role===role);if(!a)return;const messages=(currentRun.messages||[]).filter(m=>m.from_agent===role||m.to_agent===role);const events=(currentRun.events||[]).filter(e=>e.actor===role||e.target===role);$('agent-detail').innerHTML=`<h2>${esc(role)}</h2><span class="status ${esc(a.status)}">${esc(a.status)}</span><h3>Mission</h3><div class="detail-block">${esc(a.system_prompt||'No prompt recorded')}</div><h3>Tools</h3><div class="detail-block">${esc((a.tool_allowlist||[]).join(', ')||'none')}</div><h3>Activity</h3><div class="detail-block">${events.map(e=>`${esc(e.event_type)} — ${esc(e.summary)}`).join('<br>')||'No activity yet'}</div><h3>Messages</h3><div class="detail-block">${messages.map(m=>`${esc(m.message_type)} to ${esc(m.to_agent)}: ${esc(m.content)}`).join('<br><br>')||'No messages yet'}</div>`;$('agent-drawer').classList.add('open')}
function closeAgent(){$('agent-drawer').classList.remove('open')}
async function resumeRun(id,action){try{await api(`/api/runs/${id}/resume/${action}`,{method:'POST'});await showRun(id)}catch(error){alert(`Resume failed: ${error.message}`)}}
$('task-form').onsubmit=async e=>{e.preventDefault();const allowed=[...$('tools').selectedOptions].map(x=>x.value);const task={task_type:'research',task_input:{topic:$('topic').value,audience:'Developers and video viewers',goal:'Explain trade-offs with verifiable evidence'},allowed_tools:allowed,required_tools:allowed.includes('web_search')?['web_search']:[],max_agents:Number($('max-agents').value),response_schema:{type:'object',properties:{summary:{type:'string'},sources:{type:'array',items:{type:'string'}}},required:['summary','sources'],additionalProperties:false}};try{const r=await api('/api/runs',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(task)});selected=r.thread_id;await loadRuns()}catch(error){$('detail').innerHTML=`<div class="empty">Launch failed: ${esc(error.message)}</div>`}};
async function connectEvents(){const latest=await api('/api/events/latest');lastEvent=latest.sequence;const events=new EventSource(`/events?after=${lastEvent}`);events.onopen=()=>{$('connection').textContent='live';$('connection').className='status completed'};events.onmessage=e=>{const event=JSON.parse(e.data);lastEvent=Math.max(lastEvent,event.sequence);loadRuns()};events.onerror=()=>{$('connection').textContent='reconnecting';$('connection').className='status'}}loadRuns();connectEvents();
</script></body></html>"""
