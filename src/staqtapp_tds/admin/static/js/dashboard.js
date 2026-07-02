const $ = (id) => document.getElementById(id);
const setText = (id, value) => { const el = $(id); if (el) el.textContent = value ?? '—'; };
const setWidth = (id, value) => { const el = $(id); if (el) el.style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`; };
const fmt = (value, fallback = 0) => {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(value < 10 ? 2 : 1);
  return value;
};
function secondsToHMS(sec){sec=Math.max(0,Number(sec)||0);const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=Math.floor(sec%60);return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;}
function percent(x){x=Number(x)||0;return x<=1?Math.round(x*1000)/10:Math.round(x*10)/10;}
function titleCase(s){return String(s||'').replace(/[-_]/g,' ').replace(/\b\w/g,c=>c.toUpperCase());}
function bytesLabel(v){if(typeof v==='string') return v; const n=Number(v)||0; if(n>=1073741824)return (n/1073741824).toFixed(2)+' GB'; if(n>=1048576)return (n/1048576).toFixed(1)+' MB'; if(n>=1024)return (n/1024).toFixed(1)+' KB'; return n+' B';}
function snapshotAge(created){if(!created)return '—';return Math.max(0,((Date.now()/1000)-Number(created))).toFixed(1)+' sec';}
function pick(data, path, fallback){let cur=data; for(const p of path.split('.')){if(cur && Object.prototype.hasOwnProperty.call(cur,p))cur=cur[p];else return fallback;} return cur ?? fallback;}
function normalize(data){
  const obs=data.observation||data;
  return {
    active:data.active||obs.active||{},
    perf:obs.performance||{},
    storage:obs.storage||{},
    indexes:obs.indexes||{},
    behavior:obs.behavior||{},
    components:obs.components||{},
    pressure:obs.pressure||data.pressure||{},
    created:obs.created_at||data.server_time,
    uptime:obs.uptime_seconds||0,
    panel:data.panel||{},
    nativeDiagnostics:obs.native_diagnostics||data.native_diagnostics||{},
    recovery:obs.recovery||data.recovery||{}
  };
}
function updateNav(){document.querySelectorAll('.nav-pill').forEach(a=>{a.addEventListener('click',()=>{document.querySelectorAll('.nav-pill').forEach(n=>n.classList.remove('active'));a.classList.add('active');});});}
function renderNamespaces(behavior){
  const host=$('namespaces'); if(!host)return; host.innerHTML='';
  const raw=behavior.hot_namespaces||behavior.namespaces||[];
  let items=[];
  if(Array.isArray(raw)) items=raw.map((x,i)=> typeof x==='string'? {name:x,ops:Math.max(1,5-i)} : {name:x.name||x.namespace||`ns-${i+1}`,ops:x.ops||x.count||x.value||1});
  else items=Object.entries(raw).map(([name,ops])=>({name,ops}));
  if(items.length===0) items=[{name:'memory',ops:82},{name:'knowledge',ops:64},{name:'workspace',ops:38},{name:'archive',ops:24}];
  const max=Math.max(...items.map(x=>Number(x.ops)||0),1);
  items.slice(0,5).forEach(item=>{
    const pct=Math.max(4,Math.round((Number(item.ops)||0)/max*100));
    const row=document.createElement('div'); row.className='namespace-row';
    row.innerHTML=`<span title="${String(item.name)}">${String(item.name)}</span><i style="width:${pct}%"></i><b>${Number(item.ops||0).toLocaleString()}</b>`;
    host.appendChild(row);
  });
}
function renderRecommendations(data){
  const host=$('recommendations-list'); if(!host)return; host.innerHTML='';
  const n=normalize(data), perf=n.perf, storage=n.storage, indexes=n.indexes, behavior=n.behavior;
  const swiss=indexes.swiss||{};
  let list=behavior.recommendations||data.recommendations||[];
  if(!Array.isArray(list)) list=[];
  const synthetic=[];
  if((Number(swiss.average_probe||swiss.avg_probe)||0)>2.5) synthetic.push(['Swiss probe length rising','Consider rebuild or resize during a maintenance window.']);
  if((Number(behavior.compression_ratio)||1)<1.12 && storage.compression_enabled!==false) synthetic.push(['Compression ratio is low','Consider staging a config with compression disabled for tiny entries.']);
  if((Number(storage.persistence_queue_pending)||0)>50) synthetic.push(['Persistence queue pressure','Consider increasing flush capacity or scheduling maintenance.']);
  if((Number(perf.python_backend_ops)||0)>(Number(perf.native_backend_ops)||0)) synthetic.push(['Python fallback dominates','Check native extension availability and benchmark native index mode.']);
  if(!list.length && !synthetic.length) synthetic.push(['System operating normally','No measured tuning action is currently recommended.']);
  [...list.map(x=>[x.title||x.name||'Recommendation',x.detail||x.message||String(x)]),...synthetic].slice(0,4).forEach(([title,body])=>{
    const row=document.createElement('div'); row.className='reco'; row.innerHTML=`<div><b>${title}</b><span>${body}</span></div>`; host.appendChild(row);
  });
}
function renderTimeline(data){
  const host=$('timeline-list'); if(!host)return; host.innerHTML='';
  const n=normalize(data), active=n.active, perf=n.perf, behavior=n.behavior;
  const timeline=Array.isArray(perf.execution_timeline)?perf.execution_timeline.slice(-24):[];
  if(timeline.length){
    const graph=document.createElement('div'); graph.className='timeline-graph';
    graph.innerHTML='<b>Native/GIL telemetry feedback</b><div class="spark"></div><small>bars show GIL-released %, labels show native execution % over cached snapshots</small>';
    const spark=graph.querySelector('.spark');
    timeline.forEach(p=>{
      const bar=document.createElement('i');
      const gil=Math.max(2,Math.min(100,Number(p.gil_released_percent)||0));
      bar.style.height=`${gil}%`;
      bar.title=`native ${fmt(p.native_execution_percent,0)}%, GIL ${fmt(p.gil_released_percent,0)}%, transitions ${fmt(p.python_native_transitions,0)}`;
      bar.setAttribute('data-label', `${fmt(p.native_execution_percent,0)}%`);
      spark.appendChild(bar);
    });
    host.appendChild(graph);
  }
  const rows=[
    ['now','Snapshot refreshed',`Telemetry cache updated for ${active.config_id||'active RuntimeConfig'}.`],
    ['-2s',`Workload ${behavior.workload_mode||'idle'}`,`${fmt(perf.read_count,0)} reads and ${fmt(perf.write_count,0)} writes observed.`],
    ['-5s','GIL feedback',`${fmt(perf.gil_released_percent,0)}% GIL-released native work, ${fmt(perf.python_native_transitions_per_sec,0)} Python↔native transitions/sec.`],
    ['-8s','RuntimeConfig active',`${active.config_id||'rc-000'} generation ${active.generation??0} is serving new operations.`]
  ];
  rows.forEach(([t,title,body])=>{const item=document.createElement('div'); item.className='timeline-item'; item.innerHTML=`<time>${t}</time><div><b>${title}</b><span>${body}</span></div>`; host.appendChild(item);});
}

function renderNativeDiagEvents(nativeDiag){
  const host=$('native-diag-events'); if(!host)return; host.innerHTML='';
  const events=Array.isArray(nativeDiag.recent_events)?nativeDiag.recent_events.slice(-8).reverse():[];
  if(!events.length){const empty=document.createElement('div'); empty.className='diag-event-row'; empty.innerHTML='<b>No native transition events yet</b><span>Start native operations or enable diagnostics.</span>'; host.appendChild(empty); return;}
  events.forEach(ev=>{
    const row=document.createElement('div'); row.className='diag-event-row';
    const name=titleCase(ev.event_name||`event ${ev.code||0}`);
    const sub=titleCase(ev.subsystem_name||'native diagnostics');
    row.innerHTML=`<b>${name}</b><span>${sub} · seq ${fmt(ev.seq,0)} · obj ${fmt(ev.object_id,0)} · ${fmt(ev.value_a,0)}/${fmt(ev.value_b,0)}</span>`;
    host.appendChild(row);
  });
}
function applyComponentStatus(components, storage){
  const map={api:'tds_api',swiss:'swiss_index',radix:'radix_router',chunks:'chunk_manager',compression:'compression',persistence:'persistence'};
  Object.entries(map).forEach(([ui,key])=>{
    const el=$(`${ui}-status`); if(!el)return;
    let v=(components[key]&&components[key].status)||'healthy';
    if(ui==='compression') v=storage.compression_enabled===false?'disabled':'enabled';
    el.textContent=titleCase(v);
    el.style.color = String(v).includes('disabled') ? 'var(--orange)' : 'var(--green)';
  });
}
function renderPressureEngine(pressure){
  const pairs=[
    ['engine','engine_pressure'],['storage','storage_pressure'],['index','index_pressure'],['lock','lock_pressure'],
    ['ring','ring_buffer_pressure'],['memory','memory_pressure'],['bridge','bridge_pressure'],['dashboard','dashboard_pressure']
  ];
  pairs.forEach(([id,key])=>{const v=Number(pressure[key]||0); setText(`${id}-pressure`, `${fmt(v,0)}%`); setWidth(`${id}-pressure-bar`, v);});
  setText('pressure-dominant', titleCase(pressure.dominant_component||'stable'));
  const host=$('pressure-causes'); if(!host)return; host.innerHTML='';
  const causes=Array.isArray(pressure.causes)?pressure.causes.slice(0,5):[];
  if(!causes.length){const row=document.createElement('div'); row.className='diag-event-row'; row.innerHTML='<b>Stable</b><span>No elevated pressure detected from current snapshots.</span>'; host.appendChild(row); return;}
  causes.forEach((cause,i)=>{const row=document.createElement('div'); row.className='diag-event-row'; row.innerHTML=`<b>${i===0?'Dominant signal':'Supporting signal'}</b><span>${cause}</span>`; host.appendChild(row);});
}

function renderRecoveryPlanner(recovery){
  recovery = recovery || {};
  setText('recovery-status', titleCase(recovery.status || 'stable'));
  setText('recovery-primary', titleCase(recovery.primary_subsystem || 'system'));
  setText('recovery-confidence', `${fmt(Number(recovery.confidence || 0),0)}%`);
  setText('recovery-summary', recovery.summary || 'Recovery Planner is observing pressure snapshots and no action is currently required.');
  const host=$('recovery-actions'); if(host){
    host.innerHTML='';
    const actions=Array.isArray(recovery.actions)?recovery.actions.slice(0,5):[];
    if(!actions.length){
      const row=document.createElement('div'); row.className='recovery-action';
      row.innerHTML='<b>Observe only</b><span>No recovery action is recommended from the current snapshot.</span><small>automatic: no</small>';
      host.appendChild(row);
    } else {
      actions.forEach(action=>{
        const row=document.createElement('div'); row.className=`recovery-action ${action.severity||'info'}`;
        const evidence=Array.isArray(action.evidence)?action.evidence.slice(0,3).join(' '):'';
        row.innerHTML=`<b>${action.title||action.code||'Recovery action'}</b><span>${action.recommendation||''}</span><small>${titleCase(action.subsystem||'system')} · confidence ${fmt(action.confidence||0,0)}% · automatic: ${action.automatic?'yes':'no'}</small><em>${evidence}</em>`;
        host.appendChild(row);
      });
    }
  }
  const guards=$('recovery-guardrails'); if(guards){
    guards.innerHTML='';
    const list=Array.isArray(recovery.guardrails)?recovery.guardrails:[];
    (list.length?list:['Planner consumes copied snapshots only.','No automatic storage mutation is allowed.']).slice(0,4).forEach(g=>{
      const row=document.createElement('p'); row.innerHTML=`<img src="/static/icons/security.svg" alt="">${g}`; guards.appendChild(row);
    });
  }
}

function render(data){
  try{
    const n=normalize(data), active=n.active, perf=n.perf, storage=n.storage, indexes=n.indexes, behavior=n.behavior, pressure=n.pressure||{}, nativeDiag=n.nativeDiagnostics||{}, recovery=n.recovery||{};
    const swiss=indexes.swiss||{}, radix=indexes.radix||{};
    const health=(data.system_health||'HEALTHY').toString().toUpperCase();
    setText('last-update', new Date().toLocaleTimeString()); setText('side-health', titleCase(health)); setText('health-main', health); setText('health-score', health==='HEALTHY'?'99%':'72%'); setText('health-sub', health==='HEALTHY'?'All systems operational':'Review recommendations and audit events');
    setText('runtime-config', active.config_id||'rc-000'); setText('runtime-gen', `Generation ${active.generation??0}`);
    setText('reads-sec', fmt(perf.reads_per_sec ?? perf.read_count,0)); setText('writes-sec', fmt(perf.writes_per_sec ?? perf.write_count,0)); setText('avg-lookup', fmt(perf.avg_lookup_ms,0));
    setText('memory-use', bytesLabel(storage.memory_bytes||storage.memory_usage||0)); setWidth('memory-meter', storage.memory_percent||38);
    const pressureScore=Number(pressure.score ?? behavior.pressure_score ?? 0)||0;
    const pressureMode=String(pressure.mode_label || pressure.mode || behavior.pressure || 'normal').toUpperCase().replace(/_/g,' ');
    setText('pressure-score', fmt(pressureScore,0)); setText('pressure-score-large', fmt(pressureScore,0)); setText('pressure-mode', pressureMode); setText('pressure-chip', pressureMode); setWidth('pressure-meter', pressureScore);
    setText('vfs-state', titleCase(pressure.vfs_state || behavior.vfs_state || 'active'));
    setText('chunk-pending', fmt(pressure.chunk_pending_count ?? storage.chunk_pending ?? 0,0)); setText('chunk-quarantined', fmt(pressure.chunk_quarantined_count ?? storage.chunk_quarantined ?? 0,0));
    setText('snapshot-lag', fmt(pressure.snapshot_lag ?? 0,0)); setText('telemetry-dropped', fmt(pressure.telemetry_dropped_rate ?? storage.telemetry_dropped ?? 0,0));
    setText('gil-reacquire-rate', fmt(pressure.gil_reacquire_rate ?? perf.python_native_transitions ?? 0,0)); setText('swiss-probe-pressure', fmt(pressure.swiss_probe_pressure ?? 0,0));
    renderPressureEngine(pressure); renderRecoveryPlanner(recovery);
    setText('chunk-sealed', fmt(storage.chunk_sealed ?? 0,0)); setText('chunk-verified', fmt(storage.chunk_verified ?? 0,0)); setText('chunk-indexed', fmt(storage.chunk_indexed ?? 0,0)); setText('chunk-exposed', fmt(storage.chunk_exposed ?? 0,0));
    const reads=Number(perf.read_count||perf.reads_per_sec||0), writes=Number(perf.write_count||perf.writes_per_sec||0), total=Math.max(1,reads+writes);
    const readPct=Math.round(reads/total*100), writePct=Math.round(writes/total*100), idlePct=(reads+writes)===0?100:0;
    setText('workload-mode', behavior.workload_mode||((reads+writes)?(readPct>=writePct?'read-heavy':'write-heavy'):'idle'));
    setText('workload-word', titleCase(behavior.workload_mode||((reads+writes)?(readPct>=writePct?'read':'write'):'idle'))); setText('workload-pct', `${Math.max(readPct,writePct,idlePct)}%`); setText('read-pct', `${readPct}%`); setText('write-pct', `${writePct}%`); setText('idle-pct', `${idlePct}%`);
    const donut=$('donut'); if(donut) donut.style.background=`conic-gradient(var(--blue) 0 ${readPct}%, var(--orange) ${readPct}% ${readPct+writePct}%, var(--green) ${readPct+writePct}% 100%)`;
    renderNamespaces(behavior);
    setText('current-op', titleCase(behavior.current_operation || ((reads+writes)?(readPct>=writePct?'lookup':'write'):'idle'))); setText('current-op-desc', (behavior.current_operation||'idle')==='idle'?'Waiting for engine activity':'Processing cached telemetry from engine operations'); setText('op-duration', fmt(perf.avg_lookup_ms,0));
    setText('queue-pending', fmt(storage.persistence_queue_pending,0)); setText('flush-rate', `${fmt(storage.persistence_flush_rate,0)} / sec`);
    setText('read-count', fmt(perf.reads_per_sec ?? perf.read_count,0)); setText('write-count', fmt(perf.writes_per_sec ?? perf.write_count,0)); setText('delete-count', fmt(storage.deletes||perf.delete_count,0)); setText('avg-lookup2', fmt(perf.avg_lookup_ms,0)); setText('avg-insert', fmt(perf.avg_write_ms,0)); setText('avg-chunk', fmt(perf.avg_chunk_ms,0)); setText('flush-ms', fmt(perf.avg_persistence_flush_ms,0)); setText('compression-ratio', `${fmt(behavior.compression_ratio||storage.compression_ratio,1)}x`);
    setText('swiss-entries', fmt(swiss.entries||swiss.size,0)); setText('swiss-load', `${fmt(percent(swiss.load_factor),0)}%`); setWidth('swiss-load-bar', percent(swiss.load_factor)); setText('avg-probe', fmt(swiss.average_probe||swiss.avg_probe,0)); setText('max-probe', fmt(swiss.max_probe,0)); setText('tombstones', fmt(swiss.tombstones,0));
    setText('radix-nodes', fmt(radix.routers||radix.nodes,0)); setText('radix-depth', fmt(radix.average_lookup_steps||radix.average_depth,0)); setText('radix-max-depth', fmt(radix.max_depth,0));
    setText('storage-entries', fmt(storage.entries,0)); setText('chunks-created', fmt(storage.chunks_created,0)); setText('active-chunks', fmt(storage.active_chunks||storage.chunks_created,0)); setText('avg-chunk-size', bytesLabel(storage.avg_chunk_size)); setText('largest-chunk', bytesLabel(storage.largest_chunk)); setText('compression-enabled', active.compression_enabled===false||storage.compression_enabled===false?'Disabled':'Enabled'); setText('total-data-size', bytesLabel(storage.total_data_size)); setText('on-disk-size', bytesLabel(storage.on_disk_size));
    const ndc=nativeDiag.counters||{}; setText('native-diag-status', nativeDiag.degraded?'DEGRADED':(nativeDiag.enabled?'ENABLED':'DISABLED')); setText('native-diag-seq', fmt(nativeDiag.sequence,0)); setText('native-diag-build', fmt(nativeDiag.snapshot_build_ns,0)); setText('native-diag-dropped', fmt(ndc.events_dropped,0)); setText('native-diag-ring-occ', fmt(ndc.ring_occupancy,0)); setText('native-diag-ring-cap', fmt(ndc.ring_capacity,0)); setWidth('native-diag-ring-meter', (Number(ndc.ring_occupancy||0)/Math.max(1,Number(ndc.ring_capacity||1)))*100); setText('native-diag-gil', fmt(ndc.gil_released_calls,0)); setText('native-diag-transitions', fmt(ndc.python_native_transitions,0)); setText('native-diag-slot-transitions', fmt(ndc.slot_transitions,0)); setText('native-diag-index-transitions', fmt(ndc.index_transitions,0)); setText('native-diag-memory-transitions', fmt(ndc.memory_transitions,0)); renderNativeDiagEvents(nativeDiag); setText('diagnostics-status', nativeDiag.degraded?'Degraded':(nativeDiag.enabled?'Enabled':'Disabled')); setText('uptime', secondsToHMS(n.uptime)); setText('side-uptime', secondsToHMS(n.uptime)); setText('backend', String(swiss.backend||'native').includes('python')?'Python':'Native'); setText('native-exec-pct', `${fmt(perf.native_execution_percent,0)}%`); setWidth('native-exec-bar', perf.native_execution_percent||0); setText('python-exec-pct', `${fmt(perf.python_execution_percent,0)}%`); setText('gil-released-pct', `${fmt(perf.gil_released_percent,0)}%`); setText('native-transitions', fmt(perf.python_native_transitions_per_sec ?? perf.python_native_transitions,0)); setText('native-batch-ops', fmt(perf.native_batch_ops_per_sec ?? perf.native_batch_ops,0)); setText('pool-reuse', `${fmt(perf.pool_reuse_percent,0)}%`); setText('allocator-calls', fmt(perf.pool_allocator_calls,0)); setText('gil-ops', fmt(perf.gil_released_ops_per_sec ?? perf.gil_released_ops ?? perf.native_backend_ops,0)); setText('py-fallback', fmt(perf.python_backend_ops,0)); setText('snapshot-age', snapshotAge(n.created));
    applyComponentStatus(n.components, storage); renderRecommendations(data); renderTimeline(data);
  }catch(err){ setText('health-main','PANEL ERROR'); console.error(err); }
}
async function refreshDashboard(){try{const resp=await fetch('/status.json',{cache:'no-store'}); if(!resp.ok) throw new Error(`status ${resp.status}`); render(await resp.json());}catch(err){setText('health-main','DISCONNECTED'); setText('health-sub','Waiting for local admin server'); console.error(err);}}
updateNav(); refreshDashboard(); setInterval(refreshDashboard, window.STAQTAPP_REFRESH_MS || 2000);
