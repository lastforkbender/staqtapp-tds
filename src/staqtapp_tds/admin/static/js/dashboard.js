const $ = (id) => document.getElementById(id);
const tr = (value) => window.TDSI18N ? window.TDSI18N.t(value) : value;
const setText = (id, value) => { const el = $(id); if (el) el.textContent = tr(value ?? '—'); };
const setWidth = (id, value) => { const el = $(id); if (el) el.style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`; };
const clear = (el) => { if (el) el.replaceChildren(); };
const node = (tag, text, className) => { const el = document.createElement(tag); if (className) el.className = className; el.textContent = tr(text ?? ''); return el; };
function appendPairRow(host, className, title, body){ const row=document.createElement('div'); row.className=className; row.appendChild(node('b', title)); row.appendChild(node('span', body)); host.appendChild(row); return row; }
function appendTimelineRow(host, t, title, body){ const item=document.createElement('div'); item.className='timeline-item'; item.appendChild(node('time', t)); const div=document.createElement('div'); div.appendChild(node('b', title)); div.appendChild(node('span', body)); item.appendChild(div); host.appendChild(item); return item; }
function appendRecoveryAction(host, className, title, recommendation, small, evidence){ const row=document.createElement('div'); row.className=className; row.appendChild(node('b', title)); row.appendChild(node('span', recommendation)); row.appendChild(node('small', small)); if(evidence) row.appendChild(node('em', evidence)); host.appendChild(row); return row; }
const fmt = (value, fallback = 0) => {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(value < 10 ? 2 : 1);
  return value;
};
const truncateText = (value, limit = 24) => {
  const text = String(value ?? '');
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(1, limit - 1))}…`;
};
const compactCount = (value, fallback = 0) => {
  if (value === undefined || value === null || value === '') return String(fallback);
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const abs = Math.abs(n);
  const scaled = (divisor, suffix) => {
    const amount = n / divisor;
    const digits = Math.abs(amount) >= 10 ? 1 : 2;
    return `${Number(amount.toFixed(digits)).toLocaleString()}${suffix}`;
  };
  if (abs >= 1_000_000_000_000) return scaled(1_000_000_000_000, 'T');
  if (abs >= 1_000_000_000) return scaled(1_000_000_000, 'B');
  if (abs >= 1_000_000) return scaled(1_000_000, 'M');
  if (abs >= 1_000) return scaled(1_000, 'K');
  return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(abs < 10 ? 2 : 1);
};
const setCompactText = (id, value, fallback = 0) => {
  const el = $(id);
  if (!el) return;
  el.textContent = tr(compactCount(value, fallback));
  const n = Number(value);
  el.title = Number.isFinite(n) ? n.toLocaleString() : String(value ?? fallback);
};
function secondsToHMS(sec){sec=Math.max(0,Number(sec)||0);const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=Math.floor(sec%60);return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;}
function percent(x){x=Number(x)||0;return x<=1?Math.round(x*1000)/10:Math.round(x*10)/10;}
function titleCase(s){return String(s||'').replace(/[-_]/g,' ').replace(/\b\w/g,c=>c.toUpperCase());}
function bytesLabel(v){if(typeof v==='string') return v; const n=Number(v)||0; if(n>=1073741824)return (n/1073741824).toFixed(2)+' GB'; if(n>=1048576)return (n/1048576).toFixed(1)+' MB'; if(n>=1024)return (n/1024).toFixed(1)+' KB'; return n+' B';}
function snapshotAge(created){if(!created)return '—';return Math.max(0,((Date.now()/1000)-Number(created))).toFixed(1)+' sec';}
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
    recovery:obs.recovery||data.recovery||{},
    spiralRank:obs.spiral_rank||data.spiral_rank||{}
  };
}
function updateNav(){document.querySelectorAll('.nav-pill').forEach(a=>{a.addEventListener('click',()=>{document.querySelectorAll('.nav-pill').forEach(n=>n.classList.remove('active'));a.classList.add('active');});});}
function renderNamespaces(behavior){
  const host=$('namespaces'); if(!host)return; clear(host);
  const raw=behavior.hot_namespaces||behavior.namespaces||[];
  let items=[];
  if(Array.isArray(raw)) items=raw.map((x,i)=> typeof x==='string'? {name:x,ops:Math.max(1,5-i)} : {name:x.name||x.namespace||`ns-${i+1}`,ops:x.ops||x.count||x.value||1});
  else items=Object.entries(raw).map(([name,ops])=>({name,ops}));
  if(items.length===0) items=[{name:'memory',ops:82},{name:'knowledge',ops:64},{name:'workspace',ops:38},{name:'archive',ops:24}];
  const max=Math.max(...items.map(x=>Number(x.ops)||0),1);
  items.slice(0,5).forEach(item=>{
    const pct=Math.max(4,Math.round((Number(item.ops)||0)/max*100));
    const row=document.createElement('div'); row.className='namespace-row';
    const fullName=String(item.name);
    const label=node('span', truncateText(fullName, 24)); label.title=fullName;
    const bar=document.createElement('i'); bar.style.width=`${pct}%`;
    const count=node('b', compactCount(item.ops||0)); count.title=Number(item.ops||0).toLocaleString();
    row.append(label, bar, count);
    host.appendChild(row);
  });
  if (window.TDSI18N) window.TDSI18N.applyTranslations(host);
}
function renderRecommendations(data){
  const host=$('recommendations-list'); if(!host)return; clear(host);
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
    const row=document.createElement('div'); row.className='reco'; const div=document.createElement('div'); div.appendChild(node('b', title)); div.appendChild(node('span', body)); row.appendChild(div); host.appendChild(row);
  });
  if (window.TDSI18N) window.TDSI18N.applyTranslations(host);
}
function renderTimeline(data){
  const host=$('timeline-list'); if(!host)return; clear(host);
  const n=normalize(data), active=n.active, perf=n.perf, behavior=n.behavior;
  const timeline=Array.isArray(perf.execution_timeline)?perf.execution_timeline.slice(-24):[];
  if(timeline.length){
    const graph=document.createElement('div'); graph.className='timeline-graph';
    graph.appendChild(node('b','Native/GIL telemetry feedback'));
    const spark=document.createElement('div'); spark.className='spark'; graph.appendChild(spark);
    graph.appendChild(node('small','bars show GIL-released %, labels show native execution % over cached snapshots'));
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
  rows.forEach(([t,title,body])=>appendTimelineRow(host,t,title,body));
  if (window.TDSI18N) window.TDSI18N.applyTranslations(host);
}

function renderNativeDiagEvents(nativeDiag){
  const host=$('native-diag-events'); if(!host)return; clear(host);
  const events=Array.isArray(nativeDiag.recent_events)?nativeDiag.recent_events.slice(-8).reverse():[];
  if(!events.length){appendPairRow(host,'diag-event-row','No native transition events yet','Start native operations or enable diagnostics.'); return;}
  events.forEach(ev=>{
    const row=document.createElement('div'); row.className='diag-event-row';
    const name=titleCase(ev.event_name||`event ${ev.code||0}`);
    const sub=titleCase(ev.subsystem_name||'native diagnostics');
    row.appendChild(node('b', name)); row.appendChild(node('span', `${sub} · seq ${fmt(ev.seq,0)} · obj ${fmt(ev.object_id,0)} · ${fmt(ev.value_a,0)}/${fmt(ev.value_b,0)}`));
    host.appendChild(row);
  });
  if (window.TDSI18N) window.TDSI18N.applyTranslations(host);
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
  const host=$('pressure-causes'); if(!host)return; clear(host);
  const causes=Array.isArray(pressure.causes)?pressure.causes.slice(0,5):[];
  if(!causes.length){appendPairRow(host,'diag-event-row','Stable','No elevated pressure detected from current snapshots.'); return;}
  causes.forEach((cause,i)=>appendPairRow(host,'diag-event-row',i===0?'Dominant signal':'Supporting signal',String(cause)));
  if (window.TDSI18N) window.TDSI18N.applyTranslations(host);
}

function renderRecoveryPlanner(recovery){
  recovery = recovery || {};
  setText('recovery-status', titleCase(recovery.status || 'stable'));
  setText('recovery-primary', titleCase(recovery.primary_subsystem || 'system'));
  setText('recovery-confidence', `${fmt(Number(recovery.confidence || 0),0)}%`);
  setText('recovery-summary', recovery.summary || 'Recovery Planner is observing pressure snapshots and no action is currently required.');
  const host=$('recovery-actions'); if(host){
    clear(host);
    const actions=Array.isArray(recovery.actions)?recovery.actions.slice(0,5):[];
    if(!actions.length){
      appendRecoveryAction(host,'recovery-action','Observe only','No recovery action is recommended from the current snapshot.','automatic: no','');
    } else {
      actions.forEach(action=>{
        const evidence=Array.isArray(action.evidence)?action.evidence.slice(0,3).join(' '):'';
        appendRecoveryAction(host,`recovery-action ${action.severity||'info'}`,action.title||action.code||'Recovery action',action.recommendation||'',`${titleCase(action.subsystem||'system')} · confidence ${fmt(action.confidence||0,0)}% · automatic: ${action.automatic?'yes':'no'}`,evidence);
      });
    }
    if (window.TDSI18N) window.TDSI18N.applyTranslations(host);
  }
  const guards=$('recovery-guardrails'); if(guards){
    clear(guards);
    const list=Array.isArray(recovery.guardrails)?recovery.guardrails:[];
    (list.length?list:['Planner consumes copied snapshots only.','No automatic storage mutation is allowed.']).slice(0,4).forEach(g=>{
      const row=document.createElement('p'); const img=document.createElement('img'); img.src='/static/icons/security.svg'; img.alt=''; row.appendChild(img); row.appendChild(node('span', g)); guards.appendChild(row);
    });
    if (window.TDSI18N) window.TDSI18N.applyTranslations(guards);
  }
}



function renderSpiralRank(data){
  const n=normalize(data), sr=n.spiralRank||{};
  const stats=sr.last_stats||{};
  const hasStats=Object.keys(stats).length>0;
  setText('spiral-rank-status', hasStats ? titleCase(sr.status || 'ready') : 'WAITING');
  setText('spiral-rank-runs', fmt(sr.runs_total,0));
  setText('spiral-rank-path', `${fmt(sr.native_runs,0)} native · ${fmt(sr.fallback_runs,0)} fallback · observer only`);
  setText('spiral-rank-elapsed', fmt(stats.elapsed_ms ?? sr.average_elapsed_ms ?? 0,0));
  setText('spiral-rank-average', `rolling average ${fmt(sr.average_elapsed_ms ?? 0,0)} ms`);
  setText('spiral-rank-native-pct', `${fmt(sr.native_percent ?? (stats.native?100:0),0)}%`);
  setWidth('spiral-rank-native-bar', sr.native_percent ?? (stats.native?100:0));
  setText('spiral-rank-fallback-pct', `${fmt(sr.fallback_percent ?? (!stats.native&&hasStats?100:0),0)}%`);
  setText('spiral-rank-input', fmt(stats.input_count,0));
  setText('spiral-rank-ranked', fmt(stats.ranked_count ?? sr.total_ranked,0));
  setText('spiral-rank-limited', fmt(stats.limited_count,0));
  setText('spiral-rank-dropped', fmt(stats.dropped_by_limit ?? sr.total_dropped_by_limit,0));
  setText('spiral-rank-min', stats.min_score===null||stats.min_score===undefined?'—':fmt(stats.min_score,0));
  setText('spiral-rank-max', stats.max_score===null||stats.max_score===undefined?'—':fmt(stats.max_score,0));
  setText('spiral-rank-mean', stats.mean_score===null||stats.mean_score===undefined?'—':fmt(stats.mean_score,0));
  setText('spiral-rank-scoring', fmt(stats.scoring_ms,0));
  setText('spiral-rank-sorting', fmt(stats.sorting_ms,0));
  setText('spiral-rank-shaping', fmt(stats.shaping_ms,0));
  setText('spiral-rank-config', stats.config_id || '—');
  const top=$('spiral-rank-top'); if(top){
    clear(top);
    const rows=Array.isArray(sr.top_results)?sr.top_results:[];
    setText('spiral-rank-top-chip', `top ${rows.length}`);
    if(!rows.length){ appendPairRow(top,'diag-event-row','No ranked traces yet','Run Spiral Rank and publish the run to admin telemetry.'); }
    rows.slice(0,8).forEach(r=>{
      const rank=fmt(r.rank,0), score=fmt(r.score,0), conf=fmt(r.confidence,0), depth=fmt(r.depth,0);
      appendPairRow(top,'diag-event-row',`#${rank} ${r.trace_id||'trace'}`,`score ${score} · confidence ${conf} · depth ${depth} · ${r.native?'native':'python'}`);
    });
  }
  const hist=$('spiral-rank-history'); if(hist){
    clear(hist);
    const history=Array.isArray(sr.history)?sr.history.slice(-24):[];
    if(!history.length){ hist.appendChild(node('p','Waiting for Spiral Rank run history.','panel-note')); }
    else {
      const max=Math.max(...history.map(h=>Number(h.elapsed_ms)||0),1);
      const spark=document.createElement('div'); spark.className='spark spiral-rank-spark';
      history.forEach(h=>{
        const bar=document.createElement('i');
        const pct=Math.max(4,Math.min(100,(Number(h.elapsed_ms)||0)/max*100));
        bar.style.height=`${pct}%`;
        bar.title=`${fmt(h.elapsed_ms,0)} ms · ${fmt(h.ranked_count,0)} ranked · ${h.engine||'engine'}`;
        bar.setAttribute('data-label', fmt(h.ranked_count,0));
        spark.appendChild(bar);
      });
      hist.appendChild(spark);
      const latest=history[history.length-1]||{};
      appendPairRow(hist,'diag-event-row','Latest run',`${fmt(latest.elapsed_ms,0)} ms · ${fmt(latest.ranked_count,0)} ranked · ${latest.engine||'engine'}`);
    }
  }
  if (window.TDSI18N) window.TDSI18N.applyTranslations(document.getElementById('spiral-rank'));
}

function renderCompletedTelemetryPages(data){
  const n=normalize(data), perf=n.perf||{}, storage=n.storage||{}, indexes=n.indexes||{}, pressure=n.pressure||{}, nativeDiag=n.nativeDiagnostics||{};
  const ndc=nativeDiag.counters||{}, swiss=indexes.swiss||{}, radix=indexes.radix||{};
  const ringCap=Math.max(1,Number(ndc.ring_capacity||0)||1), ringOcc=Number(ndc.ring_occupancy||0)||0, ringFill=Math.min(100,(ringOcc/ringCap)*100);
  setText('snapshot-sequence', fmt(nativeDiag.sequence ?? data.sequence ?? 0,0));
  setText('snapshot-created', n.created ? new Date(Number(n.created)*1000).toLocaleString() : 'waiting for cached status');
  setText('snapshot-age-large', snapshotAge(n.created));
  setText('snapshot-build-cost', fmt(nativeDiag.snapshot_build_ns,0));
  setText('snapshot-ring-fill', fmt(ringFill,0));
  setText('snapshot-events-dropped', fmt(ndc.events_dropped,0));
  setText('snapshot-server-time', data.server_time ? new Date(Number(data.server_time)*1000).toLocaleTimeString() : '—');
  const lockPressure=Number(pressure.lock_pressure||0)||0, bridgePressure=Number(pressure.bridge_pressure||0)||0, ringPressure=Number(pressure.ring_buffer_pressure||0)||0;
  setText('lock-page-pressure', `${fmt(lockPressure,0)}%`); setWidth('lock-page-pressure-bar', lockPressure);
  setText('bridge-page-pressure', `${fmt(bridgePressure,0)}%`); setWidth('bridge-page-pressure-bar', bridgePressure);
  setText('ring-page-pressure', `${fmt(ringPressure,0)}%`); setWidth('ring-page-pressure-bar', ringPressure);
  setText('lock-contention-chip', lockPressure>70?'elevated':(lockPressure>35?'watch':'transition-fed'));
  setText('lock-page-transitions', fmt(ndc.python_native_transitions ?? perf.python_native_transitions,0));
  setText('lock-page-gil', fmt(ndc.gil_released_calls ?? perf.gil_released_ops,0));
  setText('lock-page-slot-transitions', fmt(ndc.slot_transitions,0));
  setText('lock-page-index-transitions', fmt(ndc.index_transitions,0));
  setText('compare-swiss-load', `${fmt(percent(swiss.load_factor),0)}%`);
  setText('compare-radix-depth', fmt(radix.average_lookup_steps||radix.average_depth,0));
  setCompactText('compare-storage-entries', storage.entries,0);
  setText('compare-native-exec', `${fmt(perf.native_execution_percent,0)}%`);
  setText('compare-probe-pressure', fmt(pressure.swiss_probe_pressure ?? 0,0));
  setText('compare-active-chunks', fmt(storage.active_chunks||storage.chunks_created,0));
  setText('compare-memory-pressure', `${fmt(pressure.memory_pressure ?? storage.memory_percent ?? 0,0)}%`);
  setText('compare-dashboard-pressure', `${fmt(pressure.dashboard_pressure ?? 0,0)}%`);
  renderAlertsPage(data);
  renderSpiralRank(data);
}
function renderAlertsPage(data){
  const host=$('alerts-list'); if(!host) return; clear(host);
  const n=normalize(data), pressure=n.pressure||{}, nativeDiag=n.nativeDiagnostics||{}, recovery=n.recovery||{}, ndc=nativeDiag.counters||{};
  const alerts=[];
  const pressureScore=Number(pressure.score||0)||0;
  if(pressureScore>=70) alerts.push(['critical','High pressure',`Pressure score is ${fmt(pressureScore,0)}%; dominant component ${titleCase(pressure.dominant_component||'unknown')}.`]);
  else if(pressureScore>=35) alerts.push(['warning','Pressure watch',`Pressure score is ${fmt(pressureScore,0)}%; monitor component pressures.`]);
  if(Number(ndc.events_dropped||0)>0) alerts.push(['warning','Diagnostic events dropped',`${fmt(ndc.events_dropped,0)} native diagnostic events were dropped by the loss-tolerant ring.`]);
  if(nativeDiag.degraded) alerts.push(['critical','Diagnostics degraded','Native diagnostics reported degraded state in the current snapshot.']);
  if(recovery.status && String(recovery.status).toLowerCase()!=='stable') alerts.push(['warning','Recovery planner advisory',recovery.summary||'Recovery planner recommends reviewing advisory actions.']);
  const causes=Array.isArray(pressure.causes)?pressure.causes.slice(0,3):[];
  causes.forEach(c=>alerts.push(['info','Pressure signal',String(c)]));
  if(!alerts.length) alerts.push(['info','No active alerts','Current telemetry snapshot does not contain elevated operational events.']);
  alerts.slice(0,7).forEach(([level,title,body])=>{
    const row=document.createElement('div'); row.className=`diag-event-row alert-row ${level}`;
    row.appendChild(node('b', title)); row.appendChild(node('span', body));
    host.appendChild(row);
  });
  if (window.TDSI18N) window.TDSI18N.applyTranslations(host);
  setText('alerts-chip', alerts.length && alerts[0][0]!=='info' ? 'attention' : 'ring-buffer aware');
}

function render(data){
  try{
    const n=normalize(data), active=n.active, perf=n.perf, storage=n.storage, indexes=n.indexes, behavior=n.behavior, pressure=n.pressure||{}, nativeDiag=n.nativeDiagnostics||{}, recovery=n.recovery||{};
    const swiss=indexes.swiss||{}, radix=indexes.radix||{};
    const health=(data.system_health||'HEALTHY').toString().toUpperCase();
    setText('last-update', new Date().toLocaleTimeString()); setText('side-health', titleCase(health)); setText('health-main', health); const scoreNum = health==='HEALTHY' ? 99 : 72; setText('health-score', `${scoreNum}%`); const healthRing=$('health-ring'); if(healthRing) healthRing.style.background=`conic-gradient(var(--green) 0 ${scoreNum}%, rgba(255,255,255,.12) ${scoreNum}% 100%)`; setText('health-sub', health==='HEALTHY'?'All systems operational':'Review recommendations and audit events');
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
    const reads=Number(perf.read_count||perf.reads_per_sec||0), writes=Number(perf.write_count||perf.writes_per_sec||0), maintenance=Number(perf.maintenance_count||perf.maintenance_ops||storage.maintenance_ops||0);
    const workloadTotal=reads+writes+maintenance;
    let readPct=0, writePct=0, maintenancePct=0, idlePct=100;
    if(workloadTotal>0){
      readPct=Math.round(reads/workloadTotal*100);
      writePct=Math.round(writes/workloadTotal*100);
      maintenancePct=Math.round(maintenance/workloadTotal*100);
      idlePct=Math.max(0,100-readPct-writePct-maintenancePct);
    }
    setText('workload-mode', behavior.workload_mode||((workloadTotal)?(readPct>=writePct?'read-heavy':'write-heavy'):'idle'));
    setText('workload-word', titleCase(behavior.workload_mode||((workloadTotal)?(readPct>=writePct?'read':'write'):'idle'))); setText('workload-pct', `${Math.max(readPct,writePct,maintenancePct,idlePct)}%`); setText('read-pct', `${readPct}%`); setText('write-pct', `${writePct}%`); setText('maintenance-pct', `${maintenancePct}%`); setText('idle-pct', `${idlePct}%`);
    const donut=$('donut'); if(donut) donut.style.background=`conic-gradient(var(--blue) 0 ${readPct}%, var(--orange) ${readPct}% ${readPct+writePct}%, var(--purple) ${readPct+writePct}% ${readPct+writePct+maintenancePct}%, var(--green) ${readPct+writePct+maintenancePct}% 100%)`;
    renderNamespaces(behavior);
    setText('current-op', titleCase(behavior.current_operation || ((workloadTotal)?(readPct>=writePct?'lookup':'write'):'idle'))); setText('current-op-desc', (behavior.current_operation||'idle')==='idle'?'Waiting for engine activity':'Processing cached telemetry from engine operations'); setText('op-duration', fmt(perf.avg_lookup_ms,0));
    setText('queue-pending', fmt(storage.persistence_queue_pending,0)); setText('flush-rate', `${fmt(storage.persistence_flush_rate,0)} / sec`);
    setText('read-count', fmt(perf.reads_per_sec ?? perf.read_count,0)); setText('write-count', fmt(perf.writes_per_sec ?? perf.write_count,0)); setText('delete-count', fmt(storage.deletes||perf.delete_count,0)); setText('avg-lookup2', fmt(perf.avg_lookup_ms,0)); setText('avg-insert', fmt(perf.avg_write_ms,0)); setText('avg-chunk', fmt(perf.avg_chunk_ms,0)); setText('flush-ms', fmt(perf.avg_persistence_flush_ms,0)); setText('compression-ratio', `${fmt(behavior.compression_ratio||storage.compression_ratio,1)}x`);
    setText('swiss-entries', fmt(swiss.entries||swiss.size,0)); setText('swiss-load', `${fmt(percent(swiss.load_factor),0)}%`); setWidth('swiss-load-bar', percent(swiss.load_factor)); setText('avg-probe', fmt(swiss.average_probe||swiss.avg_probe,0)); setText('max-probe', fmt(swiss.max_probe,0)); setText('tombstones', fmt(swiss.tombstones,0));
    setText('radix-nodes', fmt(radix.routers||radix.nodes,0)); setText('radix-depth', fmt(radix.average_lookup_steps||radix.average_depth,0)); setText('radix-max-depth', fmt(radix.max_depth,0));
    setText('storage-entries', fmt(storage.entries,0)); setText('chunks-created', fmt(storage.chunks_created,0)); setText('active-chunks', fmt(storage.active_chunks||storage.chunks_created,0)); setText('avg-chunk-size', bytesLabel(storage.avg_chunk_size)); setText('largest-chunk', bytesLabel(storage.largest_chunk)); setText('compression-enabled', active.compression_enabled===false||storage.compression_enabled===false?'Disabled':'Enabled'); setText('total-data-size', bytesLabel(storage.total_data_size)); setText('on-disk-size', bytesLabel(storage.on_disk_size));
    const ndc=nativeDiag.counters||{}; setText('native-diag-status', nativeDiag.degraded?'DEGRADED':(nativeDiag.enabled?'ENABLED':'DISABLED')); setText('native-diag-seq', fmt(nativeDiag.sequence,0)); setText('native-diag-build', fmt(nativeDiag.snapshot_build_ns,0)); setText('native-diag-dropped', fmt(ndc.events_dropped,0)); setText('native-diag-ring-occ', fmt(ndc.ring_occupancy,0)); setText('native-diag-ring-cap', fmt(ndc.ring_capacity,0)); setWidth('native-diag-ring-meter', (Number(ndc.ring_occupancy||0)/Math.max(1,Number(ndc.ring_capacity||1)))*100); setText('native-diag-gil', fmt(ndc.gil_released_calls,0)); setText('native-diag-transitions', fmt(ndc.python_native_transitions,0)); setText('native-diag-slot-transitions', fmt(ndc.slot_transitions,0)); setText('native-diag-index-transitions', fmt(ndc.index_transitions,0)); setText('native-diag-memory-transitions', fmt(ndc.memory_transitions,0)); renderNativeDiagEvents(nativeDiag); setText('diagnostics-status', nativeDiag.degraded?'Degraded':(nativeDiag.enabled?'Enabled':'Disabled')); setText('uptime', secondsToHMS(n.uptime)); setText('side-uptime', secondsToHMS(n.uptime)); setText('backend', String(swiss.backend||'native').includes('python')?'Python':'Native'); setText('native-exec-pct', `${fmt(perf.native_execution_percent,0)}%`); setWidth('native-exec-bar', perf.native_execution_percent||0); setText('python-exec-pct', `${fmt(perf.python_execution_percent,0)}%`); setText('gil-released-pct', `${fmt(perf.gil_released_percent,0)}%`); setText('native-transitions', fmt(perf.python_native_transitions_per_sec ?? perf.python_native_transitions,0)); setText('native-batch-ops', fmt(perf.native_batch_ops_per_sec ?? perf.native_batch_ops,0)); setText('pool-reuse', `${fmt(perf.pool_reuse_percent,0)}%`); setText('allocator-calls', fmt(perf.pool_allocator_calls,0)); setText('gil-ops', fmt(perf.gil_released_ops_per_sec ?? perf.gil_released_ops ?? perf.native_backend_ops,0)); setText('py-fallback', fmt(perf.python_backend_ops,0)); setText('snapshot-age', snapshotAge(n.created));
    applyComponentStatus(n.components, storage); renderCompletedTelemetryPages(data); renderRecommendations(data); renderTimeline(data);
  }catch(err){ setText('health-main','PANEL ERROR'); console.error(err); }
}
async function refreshDashboard(){try{const resp=await fetch('/status.json',{cache:'no-store'}); if(!resp.ok) throw new Error(`status ${resp.status}`); render(await resp.json());}catch(err){setText('health-main','DISCONNECTED'); setText('health-sub','Waiting for local admin server'); console.error(err);}}
updateNav(); refreshDashboard();
window.TDSDashboardRefresh = { timer:null, restart(){ if(this.timer){ clearInterval(this.timer); this.timer=null; } const ms = window.TDSBrowserSettings ? window.TDSBrowserSettings.getRefreshMS() : (window.STAQTAPP_REFRESH_MS || 2000); if(ms>0){ this.timer=setInterval(refreshDashboard, ms); } } };
window.TDSDashboardRefresh.restart();
