"""Self-contained Hermes management UI served by OpenAkita."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes 节点管理</title><style>
body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f6f7fb;color:#182033}.wrap{max-width:1100px;margin:auto;padding:24px}
h1{margin:0 0 18px}.card{background:white;border:1px solid #e3e7ef;border-radius:12px;padding:18px;margin-bottom:16px;box-shadow:0 2px 8px #0000000a}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}label{display:block;font-size:13px;color:#586174;margin-bottom:5px}
input,select{width:100%;box-sizing:border-box;padding:10px;border:1px solid #cfd5df;border-radius:8px;background:white}button{border:0;border-radius:8px;padding:10px 14px;cursor:pointer;background:#2563eb;color:white;margin-right:8px}.danger{background:#dc2626}.secondary{background:#64748b}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.node{border-top:1px solid #edf0f5;padding:12px 0}.ok{color:#15803d}.bad{color:#b91c1c}.muted{color:#667085;font-size:13px}@media(max-width:720px){.grid{grid-template-columns:1fr}}
</style></head><body><div class="wrap"><h1>Hermes 节点与 Agent 路由</h1>
<div class="card"><h2>添加 / 更新节点</h2><div class="grid">
<div><label>节点 ID</label><input id="id" placeholder="hermes-1"></div><div><label>名称</label><input id="name" placeholder="客服 Hermes"></div>
<div><label>Base URL</label><input id="base_url" placeholder="http://hermes-1:8000"></div><div><label>API Key 环境变量</label><input id="api_key_env" placeholder="HERMES_1_API_KEY"></div>
<div><label>优先级</label><input id="priority" type="number" value="10"></div><div><label>权重</label><input id="weight" type="number" value="1"></div>
<div><label>最大并发</label><input id="max_concurrency" type="number" value="4"></div><div><label>超时（秒）</label><input id="timeout_seconds" type="number" value="180"></div>
<div><label>能力（逗号分隔）</label><input id="capabilities" value="text,tools"></div><div><label>标签（逗号分隔）</label><input id="tags"></div></div><p><button onclick="saveNode()">保存节点</button></p></div>
<div class="card"><h2>节点列表</h2><div id="nodes" class="muted">加载中…</div></div>
<div class="card"><h2>Agent 绑定</h2><div class="grid">
<div><label>Agent Profile ID</label><input id="profile_id" value="default"></div><div><label>运行方式</label><select id="runtime_provider"><option value="local">本地 OpenAkita</option><option value="hermes">Hermes</option><option value="auto">自动（Hermes 失败回退本地）</option></select></div>
<div><label>Hermes 节点（逗号分隔）</label><input id="hermes_node_ids"></div><div><label>路由策略</label><select id="routing"><option value="priority">优先级</option><option value="primary_backup">主备</option><option value="weighted">权重</option><option value="round_robin">轮询</option><option value="least_connections">最少连接</option></select></div>
<div><label>所需能力（逗号分隔）</label><input id="required_capabilities"></div><div><label>Hermes 失败回退</label><select id="fallback"><option value="true">启用</option><option value="false">禁用</option></select></div></div>
<p><button onclick="loadBinding()" class="secondary">读取绑定</button><button onclick="saveBinding()">保存绑定</button></p><div id="binding_status" class="muted"></div></div></div>
<script>
const api='/api/hermes'; const csv=v=>v.split(',').map(x=>x.trim()).filter(Boolean); const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
async function j(url,opt){const r=await fetch(url,opt);const d=await r.json().catch(()=>({detail:r.statusText}));if(!r.ok)throw Error(d.detail||r.statusText);return d}
async function refresh(){const d=await j(api+'/nodes');nodes.innerHTML=d.nodes.length?d.nodes.map(n=>`<div class="node"><div class="row"><b>${esc(n.name)}</b><code>${esc(n.id)}</code><span class="${n.health_status==='healthy'?'ok':'bad'}">${esc(n.health_status)}</span></div><div class="muted">${esc(n.base_url)} · 并发 ${n.current_inflight}/${n.max_concurrency} · 优先级 ${n.priority}</div><p><button onclick="testNode('${esc(n.id)}')">测试</button><button class="secondary" onclick="toggleNode('${esc(n.id)}',${!n.enabled})">${n.enabled?'停用':'启用'}</button><button class="danger" onclick="removeNode('${esc(n.id)}')">删除</button></p></div>`).join(''):'暂无节点'}
async function saveNode(){const idv=id.value.trim();const p={id:idv,name:name.value.trim(),base_url:base_url.value.trim(),api_key_env:api_key_env.value.trim(),enabled:true,priority:+priority.value,weight:+weight.value,capabilities:csv(capabilities.value),tags:csv(tags.value),max_concurrency:+max_concurrency.value,timeout_seconds:+timeout_seconds.value};try{await j(api+'/nodes/'+encodeURIComponent(idv),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})}catch(e){if(String(e).includes('not found'))await j(api+'/nodes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});else throw e}await refresh()}
async function testNode(x){const d=await j(api+'/nodes/'+encodeURIComponent(x)+'/test',{method:'POST'});alert(d.ok?'连接成功':'连接失败: '+JSON.stringify(d.result));await refresh()}
async function toggleNode(x,on){await j(api+'/nodes/'+encodeURIComponent(x)+'/'+(on?'enable':'disable'),{method:'POST'});await refresh()}
async function removeNode(x){if(confirm('确定删除 '+x+'？')){await j(api+'/nodes/'+encodeURIComponent(x),{method:'DELETE'});await refresh()}}
async function loadBinding(){const d=await j(api+'/agents/'+encodeURIComponent(profile_id.value.trim()));const b=d.binding;runtime_provider.value=b.runtime_provider;hermes_node_ids.value=(b.hermes_node_ids||[]).join(',');routing.value=b.hermes_routing_policy;required_capabilities.value=(b.required_capabilities||[]).join(',');fallback.value=String(b.hermes_fallback_enabled);binding_status.textContent='已读取'}
async function saveBinding(){const p={runtime_provider:runtime_provider.value,hermes_node_ids:csv(hermes_node_ids.value),hermes_routing_policy:routing.value,required_capabilities:csv(required_capabilities.value),hermes_fallback_enabled:fallback.value==='true'};await j(api+'/agents/'+encodeURIComponent(profile_id.value.trim()),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});binding_status.textContent='已保存'}
refresh();</script></body></html>'''


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def hermes_manager_ui() -> HTMLResponse:
    return HTMLResponse(_PAGE)
