  marked.setOptions({ breaks: true, gfm: true });

  // ── Estado ──────────────────────────────────────────────────
  let sessionId = localStorage.getItem('apoloSessionId') || (() => {
    const id = crypto.randomUUID();
    localStorage.setItem('apoloSessionId', id);
    return id;
  })();

  let busy = false;
  let currentAbort = null;     // permite Parar a geração em andamento
  let lastUserText = '';       // permite Regenerar a última resposta
  let lastNeedsWeb = false;
  let lastSmart = false;
  let pendingImage = '';       // data URL da imagem anexada (visão)
  let lastImage = '';
  let visionAvailable = false; // há modelo de visão instalado?
  let useWeb = false;
  let useResearch = false;
  let useSmart = false;     // modo inteligente (modelo 14b)
  let useAgent = false;     // modo agente (escreve+executa código)
  let useMulti = false;     // modo multi-agente (Researcher + Analyst + Coder)
  let isLearning = false;
  let learnPoll = null;
  let dashOpen = false;

  // ── Helpers ─────────────────────────────────────────────────
  function autoResize(el) { el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,140)+'px'; }
  function handleKey(e) { if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); sendMessage(); } }
  function scrollBottom() { const m=document.getElementById('messages'); m.scrollTop=m.scrollHeight; }
  function escHtml(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function renderMd(t) { try{ return DOMPurify.sanitize(marked.parse(t||'')); } catch{ return escHtml(t||''); } }

  function toggleWeb() {
    useWeb = !useWeb;
    document.getElementById('web-btn').classList.toggle('active', useWeb);
    if (useWeb && useResearch) { useResearch = false; document.getElementById('research-btn').classList.remove('active'); }
  }

  function toggleSmart() {
    useSmart = !useSmart;
    document.getElementById('smart-btn').classList.toggle('active', useSmart);
  }

  function toggleAgent() {
    useAgent = !useAgent;
    document.getElementById('agent-btn').classList.toggle('active', useAgent);
    if (useAgent && useResearch) { useResearch = false; document.getElementById('research-btn').classList.remove('active'); }
  }

  function toggleResearch() {
    useResearch = !useResearch;
    document.getElementById('research-btn').classList.toggle('active', useResearch);
    if (useResearch && useWeb) { useWeb = false; document.getElementById('web-btn').classList.remove('active'); }
    if (useResearch && useMulti) { useMulti = false; document.getElementById('multi-btn').classList.remove('active'); }
    const input = document.getElementById('input');
    input.placeholder = useResearch
      ? '🔬 Pesquisa profunda: faça uma pergunta complexa e veja o A.P.O.L.O. investigar...'
      : 'Pergunte qualquer coisa sobre código, arquitetura, cloud...';
  }

  function toggleMulti() {
    useMulti = !useMulti;
    document.getElementById('multi-btn').classList.toggle('active', useMulti);
    if (useMulti && useResearch) { useResearch = false; document.getElementById('research-btn').classList.remove('active'); }
    if (useMulti && useAgent) { useAgent = false; document.getElementById('agent-btn').classList.remove('active'); }
    const input = document.getElementById('input');
    input.placeholder = useMulti
      ? '🤝 Multi-agente: descreva uma tarefa complexa — Researcher, Analyst e Coder trabalham juntos...'
      : 'Pergunte qualquer coisa sobre código, arquitetura, cloud...';
  }

  function activateResearchFromCard() {
    if (!useResearch) toggleResearch();
    document.getElementById('input').focus();
  }

  // ── Aprendizado ─────────────────────────────────────────────
  let _prevTotalLearned = 0;

  function toggleLearnDash() {
    dashOpen = !dashOpen;
    document.getElementById('learn-dashboard').classList.toggle('open', dashOpen);
    if (dashOpen) loadActivity();
  }

  async function startLearning() {
    const btnStart = document.getElementById('btn-start');
    btnStart.disabled = true;
    btnStart.textContent = '...';
    try {
      await fetch('/api/learning/start', { method: 'POST' });
      isLearning = true;
      if (!learnPoll) learnPoll = setInterval(refreshLearnStatus, 3000);
      refreshLearnStatus();
    } catch(e) { console.error(e); }
    updateLearnUI();
  }

  async function stopLearning() {
    const btnStop = document.getElementById('btn-stop');
    btnStop.disabled = true;
    try {
      await fetch('/api/learning/stop', { method: 'POST' });
      isLearning = false;
      if (learnPoll) { clearInterval(learnPoll); learnPoll = null; }
    } catch(e) { console.error(e); }
    updateLearnUI();
  }

  function updateLearnUI() {
    const toggle = document.getElementById('learn-toggle');
    const sub    = document.getElementById('learn-sub');
    const btnStart = document.getElementById('btn-start');
    const btnStop  = document.getElementById('btn-stop');
    toggle.classList.toggle('active', isLearning);
    sub.textContent = isLearning ? '7 agentes estudando autonomamente...' : '7 agentes · clique para expandir';
    if (btnStart) { btnStart.disabled = isLearning; btnStart.textContent = isLearning ? '▶ Aprendendo...' : '▶ Iniciar'; }
    if (btnStop)  { btnStop.disabled = !isLearning; }
  }

  // Aplica um objeto de status do aprendizado na UI. Chamado tanto pelo poll
  // (refreshLearnStatus) quanto pelo push SSE (startLearnSSE → applyLearnStatus).
  // É declaração de função top-level, portanto global — o enhancements.js a
  // enxerga. (Antes ela não existia: o onmessage do SSE chamava applyLearnStatus
  // inexistente, dava ReferenceError silencioso e o painel ficava congelado.)
  function applyLearnStatus(d) {
    if (!d) return;
    isLearning = d.running;
    updateLearnUI();

    if (d.current_topic) document.getElementById('learn-now-topic').textContent = d.current_topic;
    if (d.current_source) document.getElementById('learn-now-src').textContent = d.current_source;
    document.getElementById('stat-today').textContent = d.learned_today ?? 0;
    document.getElementById('stat-total').textContent = d.total_learned ?? 0;
    document.getElementById('stat-speed').textContent = d.throughput_hour > 0 ? d.throughput_hour : '—';
    document.getElementById('stat-queue').textContent = d.queue_depth ?? 0;

    // Atualiza badge kb-count na sidebar
    const total = d.total_learned ?? 0;
    if (total > 0) document.getElementById('kb-count').textContent = total;

    // Auto-refresh: detecta novos itens aprendidos
    if (total > _prevTotalLearned && _prevTotalLearned > 0) {
      loadActivity();
      if (document.getElementById('knowledge-overlay').classList.contains('open')) {
        loadKnowledgeItems();
      }
    }
    if (total > 0) _prevTotalLearned = total;

    if (d.activity?.length) renderActivityFeed(d.activity);
    if (d.agents?.length) renderAgents(d.agents);
    renderNextStudies(d.next_studies);
  }

  async function refreshLearnStatus() {
    try {
      const d = await fetch('/api/learning/status').then(r=>r.json());
      applyLearnStatus(d);
    } catch {}
  }

  function renderNextStudies(studies) {
    const box = document.getElementById('next-studies');
    const list = document.getElementById('next-studies-list');
    if (!studies?.length) { box.classList.remove('show'); return; }
    box.classList.add('show');
    list.innerHTML = studies.slice(0,6).map(s =>
      `<div class="next-study-item" title="${escHtml(s)}">→ ${escHtml(s)}</div>`).join('');
  }

  async function loadActivity() {
    try {
      const data = await fetch('/api/learning/history').then(r=>r.json());
      if (!data.length) return;
      const feed = data.map(item => ({
        time: item.studied_at?.substring(11,16) || '',
        topic: item.topic,
        url: item.url || '',
        category: item.category || 'web_search',
      }));
      renderActivityFeed(feed);
      // Atualiza stats
      const status = await fetch('/api/learning/status').then(r=>r.json());
      document.getElementById('stat-today').textContent = status.learned_today ?? 0;
      document.getElementById('stat-total').textContent = status.total_learned ?? 0;
    } catch {}
  }

  function renderActivityFeed(items) {
    const feed = document.getElementById('activity-feed');
    if (!items.length) { feed.innerHTML = '<div style="font-size:10px;color:#333;padding:4px">Nenhuma atividade ainda</div>'; return; }
    feed.innerHTML = items.slice(0,10).map(a => `
      <div class="activity-item">
        <span class="activity-time">${escHtml(a.time)}</span>
        <span class="activity-cat cat-${a.category}">${catLabel(a.category)}</span>
        <span class="activity-topic">${escHtml(a.topic?.replace('[A.P.O.L.O.] ','').replace('[Apolo Study] ','').replace('[Auto] ','').replace('[Tendência] ',''))}</span>
      </div>`).join('');
  }

  function catLabel(cat) {
    const map = { official_doc: 'doc', user_question: 'user', tech_trend: 'trend', synthesis: 'síntese', web_search: 'web', github: 'github', self_directed: '🎯 auto' };
    return map[cat] || 'web';
  }

  function renderAgents(agents) {
    if (!agents?.length) return;
    agents.forEach(a => {
      const card = document.getElementById('ag-' + a.name);
      if (!card) return;
      card.classList.toggle('running', !!a.active);
      const topicEl = card.querySelector('.agent-topic');
      if (topicEl) topicEl.textContent = a.current_topic || (a.active ? 'processando...' : 'aguardando...');
    });
  }

  async function studyNow() {
    const input = document.getElementById('study-input');
    const topic = input.value.trim();
    if (!topic) return;
    const btn = document.getElementById('study-btn');
    btn.disabled = true;
    btn.textContent = '⏳';
    document.getElementById('learn-now-topic').textContent = topic;
    document.getElementById('learn-now-src').textContent = 'processando...';
    try {
      const res = await fetch('/api/learning/study-now', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic }),
      });
      const data = await res.json();
      if (data.ok) {
        document.getElementById('learn-now-topic').textContent = '✓ ' + topic;
        document.getElementById('learn-now-src').textContent = data.url || '';
        input.value = '';
        await loadActivity();
      } else {
        document.getElementById('learn-now-src').textContent = 'erro ao estudar';
      }
    } catch(e) {
      document.getElementById('learn-now-src').textContent = 'erro: ' + e.message;
    }
    btn.disabled = false;
    btn.textContent = '▶ Ir';
  }

  // ── Sessões ──────────────────────────────────────────────────
  function newChat() {
    closeCoder();
    fetch(`/api/session/${sessionId}`, { method: 'DELETE' });
    sessionId = crypto.randomUUID();
    localStorage.setItem('apoloSessionId', sessionId);
    document.getElementById('messages').innerHTML = '';
    const es = document.createElement('div');
    es.id = 'empty-state';
    es.innerHTML = `
      <div class="hero-glow"></div>
      <div class="sun-big">☀️</div>
      <h2>Nova conversa</h2>
      <div class="subtitle">Pronto quando você estiver</div>
      <p>Pergunte qualquer coisa, ou use uma das capacidades do A.P.O.L.O. abaixo.</p>
      <div class="cap-cards">
        <div class="cap-card" onclick="activateResearchFromCard()" title="Ativar Pesquisa Profunda">
          <div class="cap-ico">🔬</div><div class="cap-card-title">Pesquisa Profunda</div>
          <div class="cap-card-desc">Decompõe, investiga memória + web e responde com fontes</div></div>
        <div class="cap-card" onclick="openReview()" title="Abrir Code Review">
          <div class="cap-ico">🔍</div><div class="cap-card-title">Code Review</div>
          <div class="cap-card-desc">Revisa seu código com as boas práticas que estudou</div></div>
        <div class="cap-card" onclick="toggleLearnDash()" title="Abrir painel de aprendizado">
          <div class="cap-ico">♻️</div><div class="cap-card-title">Aprende sozinho</div>
          <div class="cap-card-desc">7 agentes estudando 24/7 com currículo auto-dirigido</div></div>
        <div class="cap-card" onclick="openMind()" title="Ver a mente do A.P.O.L.O.">
          <div class="cap-ico">🧠</div><div class="cap-card-title">Mente do A.P.O.L.O.</div>
          <div class="cap-card-desc">Veja tudo o que ele já sabe — por categoria e fonte</div></div>
      </div>`;
    document.getElementById('messages').appendChild(es);
    loadSessions();
  }

  async function loadSessions() {
    try {
      const data = await fetch('/api/sessions').then(r=>r.json());
      const list = document.getElementById('sessions-list');
      if (!data.length) { list.innerHTML='<div style="padding:8px 10px;font-size:10px;color:#2a2a2a">Nenhuma conversa ainda</div>'; return; }
      list.innerHTML = data.map(s=>`
        <div class="session-item ${s.session_id===sessionId?'active':''}"
             onclick="resumeSession('${s.session_id}')" title="${escHtml(s.first_message)}">
          💬 ${escHtml(s.title || s.first_message)}
        </div>`).join('');
    } catch {}
  }

  let searchTimer = null;
  function onSearchInput() {
    clearTimeout(searchTimer);
    const q = document.getElementById('session-search').value.trim();
    if (!q) { loadSessions(); return; }
    searchTimer = setTimeout(() => runSessionSearch(q), 250);
  }

  async function runSessionSearch(q) {
    try {
      const data = await fetch('/api/sessions/search?q=' + encodeURIComponent(q)).then(r=>r.json());
      const list = document.getElementById('sessions-list');
      const res = data.results || [];
      if (!res.length) { list.innerHTML = '<div style="padding:8px 10px;font-size:10px;color:#2a2a2a">Nada encontrado</div>'; return; }
      list.innerHTML = res.map(s=>`
        <div class="session-item ${s.session_id===sessionId?'active':''}"
             onclick="resumeSession('${s.session_id}')" title="${escHtml(s.snippet)}">
          💬 ${escHtml(s.title)}
          <div style="font-size:9px;color:#555;margin-top:2px;line-height:1.3">${escHtml(s.snippet)}</div>
        </div>`).join('');
    } catch {}
  }

  async function exportSessionMd() {
    if (!sessionId) { alert('Nenhuma conversa ativa.'); return; }
    try {
      const resp = await fetch(`/api/session/${sessionId}/export`);
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      const cd = resp.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="([^"]+)"/);
      a.download = m ? m[1] : 'apolo_conversa.md';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(a.href);
    } catch (e) { alert('Falha ao exportar conversa'); }
  }

  async function exportBackup() {
    try {
      const resp = await fetch('/api/export');
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      const cd = resp.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="([^"]+)"/);
      a.download = m ? m[1] : 'apolo_backup.json';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(a.href);
    } catch (e) { alert('Falha ao exportar backup'); }
  }

  async function importBackup(ev) {
    const file = ev.target.files[0];
    if (!file) return;
    if (!confirm(`Restaurar "${file.name}"? Itens já existentes são ignorados (não duplica).`)) {
      ev.target.value = ''; return;
    }
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const r = await fetch('/api/import', {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data)
      }).then(r=>r.json());
      if (r.ok) {
        const a = r.added;
        alert(`✓ Backup restaurado:\n${a.messages} mensagens · ${a.sessions} conversas · ${a.learned_topics} tópicos` +
              (r.knowledge_restored ? `\n${r.knowledge_restored} artigos de conhecimento` : ''));
        loadSessions();
      } else {
        alert('Falha ao importar: ' + (r.error || 'erro'));
      }
    } catch (e) { alert('Arquivo inválido: ' + e.message); }
    ev.target.value = '';
  }

  // ── A.P.O.L.O. Coder (Claude Code interno) ───────────────────
  function openCoder() {
    document.getElementById('coder-overlay').classList.add('show');
    document.getElementById('coder-open-btn').classList.add('active');
    refreshCoderTree();
  }
  function closeCoder() {
    document.getElementById('coder-overlay').classList.remove('show');
    document.getElementById('coder-open-btn').classList.remove('active');
  }
  function isCoderOpen() { return document.getElementById('coder-overlay').classList.contains('show'); }

  let coderSmart = false;
  function setCoderSmart(on) {
    coderSmart = on;
    const b = document.getElementById('coder-smart-btn');
    if (coderSmart) { b.textContent = '🧠 14b'; b.style.borderColor = '#fbbf24'; b.style.color = '#fbbf24'; }
    else { b.textContent = '🧠 Leve'; b.style.borderColor = '#2a2a33'; b.style.color = '#777'; }
  }
  function toggleCoderSmart() { setCoderSmart(!coderSmart); }

  async function refreshCoderTree() {
    try {
      const d = await fetch('/api/coder/files').then(r=>r.json());
      document.getElementById('coder-root').textContent = d.root || '';
      const treeEl = document.getElementById('coder-tree');
      const files = d.files || [];
      if (files.length) {
        treeEl.innerHTML = files.map(f =>
          `<div class="coder-file" onclick="viewCoderFile('${escHtml(f)}')" style="cursor:pointer;padding:1px 0" title="Ver ${escHtml(f)}">📄 ${escHtml(f)}</div>`
        ).join('');
      } else {
        treeEl.textContent = d.tree || '(vazio)';
      }
      renderCoderChanges(d.changes || []);
      refreshCoderGit();
      refreshCoderLessons();
      refreshCoderTasks();
    } catch {}
  }

  // ── Diário de bordo do Coder (tarefas executadas + taxa de sucesso) ───────
  async function refreshCoderTasks() {
    const box = document.getElementById('coder-tasks');
    if (!box) return;
    try {
      const d = await fetch('/api/coder/tasks?limit=8').then(r=>r.json());
      const st = d.stats || {};
      const statsEl = document.getElementById('coder-tasks-stats');
      if (statsEl) {
        let trend = '';
        if (st.trend !== null && st.trend !== undefined) {
          trend = st.trend > 0 ? ' ↗' : st.trend < 0 ? ' ↘' : ' →';
        }
        statsEl.textContent = st.total
          ? `(${st.total}${st.success_rate !== null && st.success_rate !== undefined ? ` · ${st.success_rate}% ✓${trend}` : ''})` : '';
        statsEl.title = (st.recent_rate !== null && st.recent_rate !== undefined && st.prev_rate !== null && st.prev_rate !== undefined)
          ? `Tendência: últimas 10 tarefas ${st.recent_rate}% vs 10 anteriores ${st.prev_rate}% — as lições estão funcionando?` : '';
        statsEl.style.color = st.trend > 0 ? '#4ade80' : st.trend < 0 ? '#f87171' : '#555';
      }
      const tasks = d.tasks || [];
      if (!tasks.length) {
        box.innerHTML = '<div style="color:#444;padding:4px 0">Nenhuma tarefa executada ainda.</div>';
        return;
      }
      box.innerHTML = tasks.map(t => {
        const icon = t.reverted ? '↩️' : (t.wrote ? '✅' : '💬');
        const dur = t.duration_s >= 60 ? `${Math.round(t.duration_s/60)}min` : `${Math.round(t.duration_s||0)}s`;
        const tip = `${escHtml(t.task)}&#10;${t.steps} passo(s) · ${dur} · ${escHtml(t.model||'')}${t.reverted ? '&#10;↩️ revertida pela guarda de regressão' : ''}`;
        return `<div style="display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid #16161c">
          <span>${icon}</span>
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:${t.reverted?'#f87171':'#a8a8b0'}" title="${tip}">${escHtml(t.task)}</span>
          <span style="color:#555;flex-shrink:0">${_relTime(t.created_at)}</span>
        </div>`;
      }).join('');
    } catch {}
  }

  // ── Memória de lições do Coder (autoaprendizado) ──────────────────────────
  async function refreshCoderLessons() {
    const box = document.getElementById('coder-lessons');
    if (!box) return;
    try {
      const d = await fetch('/api/coder/lessons').then(r=>r.json());
      const cnt = document.getElementById('coder-lessons-count');
      if (cnt) cnt.textContent = d.count ? `(${d.count})` : '';
      const lessons = d.lessons || [];
      if (!lessons.length) {
        box.innerHTML = '<div style="color:#444;padding:4px 0">Nenhuma lição ainda — o Coder aprende ao concluir tarefas.</div>';
        return;
      }
      const icons = {regression:'🛡️', failure:'✗', reflection:'💡'};
      const kinds = {regression:'regressão revertida', failure:'falha', reflection:'reflexão pós-tarefa'};
      box.innerHTML = lessons.map(l=>`
        <div style="display:flex;align-items:flex-start;gap:6px;padding:4px 0;border-bottom:1px solid #16161c">
          <span title="${escHtml(kinds[l.kind]||l.kind)}">${icons[l.kind]||'•'}</span>
          <span style="flex:1;line-height:1.4;color:#a8a8b0" title="Tarefa: ${escHtml(l.task)}&#10;${escHtml(l.created_at)} · usada ${l.hits}×">${escHtml(l.lesson)}</span>
          <span onclick="deleteCoderLesson(${l.id})" title="Esquecer esta lição" style="cursor:pointer;color:#f87171">🗑️</span>
        </div>`).join('');
    } catch {}
  }

  async function deleteCoderLesson(id) {
    if (!confirm('Esquecer esta lição? O Coder não a verá mais nas próximas tarefas.')) return;
    await fetch('/api/coder/lessons/' + id, {method:'DELETE'});
    refreshCoderLessons();
  }

  async function refreshCoderGit() {
    const el = document.getElementById('coder-git');
    if (!el) return;
    try {
      const g = await fetch('/api/coder/git').then(r=>r.json());
      if (!g.is_repo) { el.innerHTML = '<span style="color:#444">⎇ não é um repositório git</span>'; return; }
      const dot = g.dirty ? '<span style="color:#facc15">●</span>' : '<span style="color:#4ade80">●</span>';
      el.innerHTML = `${dot} <b style="color:#aaa">⎇ ${escHtml(g.branch || '?')}</b> ${g.dirty ? '· alterações pendentes' : '· limpo'}`
        + (parseInt(g.ahead)>0 ? ` · ${g.ahead} à frente` : '')
        + (g.dirty ? ' · <span onclick="viewGitDiff()" style="cursor:pointer;color:#5b9cff">ver diff</span>'
                   + ' · <span onclick="coderGitCommit()" style="cursor:pointer;color:#4ade80" title="Commit com mensagem gerada pelo A.P.O.L.O. (nunca faz push)">💾 commit</span>' : '');
    } catch { el.innerHTML = ''; }
  }

  async function coderGitCommit() {
    if (!confirm('Commitar TODAS as alterações do workspace?\nA mensagem é gerada automaticamente pelo modelo leve (nunca faz push).')) return;
    const el = document.getElementById('coder-git');
    const prev = el.innerHTML;
    el.innerHTML = '<span style="color:#888">💾 gerando mensagem e commitando…</span>';
    try {
      const d = await fetch('/api/coder/commit', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:'{}'}).then(r=>r.json());
      if (d.ok) alert('✅ Commit criado:\n\n' + d.message);
      else { alert('✗ ' + (d.error || 'falhou')); el.innerHTML = prev; }
    } catch(e) { alert('✗ ' + e.message); el.innerHTML = prev; }
    refreshCoderGit(); refreshCoderTree();
  }

  async function viewGitDiff() {
    try {
      const d = await fetch('/api/coder/git/diff').then(r=>r.json());
      let ov = document.getElementById('coder-fileview');
      if (!ov) { ov = document.createElement('div'); ov.id='coder-fileview';
        ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:210;display:flex;align-items:center;justify-content:center';
        ov.onclick=(e)=>{if(e.target===ov)ov.remove();}; document.body.appendChild(ov); }
      const lines = (d.diff||'').split('\n').map(l=>{
        let c='#7a7a85';
        if(l.startsWith('+')&&!l.startsWith('+++'))c='#4ade80';
        else if(l.startsWith('-')&&!l.startsWith('---'))c='#f87171';
        else if(l.startsWith('@@'))c='#5b9cff';
        return `<span style="color:${c}">${escHtml(l)||' '}</span>`;
      }).join('\n');
      ov.innerHTML = `<div style="background:#0b0b0f;border:1px solid #23232c;border-radius:12px;width:min(820px,94vw);height:min(640px,88vh);display:flex;flex-direction:column;padding:14px 16px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <span style="color:#5b9cff;font-size:13px">⎇ git diff</span>
          <button onclick="document.getElementById('coder-fileview').remove()" style="background:#1a1a22;border:1px solid #2a2a33;color:#aaa;border-radius:6px;padding:3px 9px;cursor:pointer">✕</button>
        </div>
        <pre style="flex:1;overflow:auto;margin:0;background:#08080b;border:1px solid #1c1c24;border-radius:8px;padding:12px;font-size:10.5px;line-height:1.35;white-space:pre">${lines}</pre>
      </div>`;
    } catch { alert('Falha ao obter o diff'); }
  }

  function renderCoderChanges(changes) {
    const box = document.getElementById('coder-changes');
    const undoAll = document.getElementById('coder-undo-all');
    if (!changes.length) { box.innerHTML = '<div style="color:#444;padding:4px 0">Nenhuma alteração ainda.</div>'; undoAll.style.display='none'; return; }
    undoAll.style.display = 'inline';
    box.innerHTML = changes.map(c=>`
      <div style="display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid #16161c">
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.is_new?'🆕':'✏️'} ${escHtml(c.path)}</span>
        <span style="color:#4ade80">+${c.added}</span><span style="color:#f87171">-${c.removed}</span>
        <span onclick="undoCoderFile('${escHtml(c.path)}')" title="Desfazer este arquivo" style="cursor:pointer;color:#f87171">↩️</span>
      </div>`).join('');
  }

  async function undoCoderFile(path) {
    await fetch('/api/coder/undo', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
    refreshCoderTree();
  }

  async function undoCoderAll() {
    if (!confirm('Descartar TODAS as alterações desta sessão?')) return;
    await fetch('/api/coder/undo', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({all:true})});
    refreshCoderTree();
  }

  // ── Histórico de comandos do terminal (seta ↑↓) ───────────────────────────
  const _CMD_HISTORY_KEY = 'apolo-cmd-history';
  let _cmdHistory = JSON.parse(localStorage.getItem(_CMD_HISTORY_KEY) || '[]');
  let _cmdHistIdx = -1;  // -1 = posição atual (digitando novo cmd)

  function _saveCmdHistory(cmd) {
    _cmdHistory = [cmd, ..._cmdHistory.filter(c => c !== cmd)].slice(0, 60);
    localStorage.setItem(_CMD_HISTORY_KEY, JSON.stringify(_cmdHistory));
    _cmdHistIdx = -1;
  }

  function _onCmdKey(e) {
    const input = document.getElementById('coder-cmd');
    if (e.key === 'Enter') { runCoderCmd(); return; }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (_cmdHistIdx < _cmdHistory.length - 1) {
        _cmdHistIdx++;
        input.value = _cmdHistory[_cmdHistIdx];
        requestAnimationFrame(() => input.setSelectionRange(input.value.length, input.value.length));
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (_cmdHistIdx > 0) {
        _cmdHistIdx--;
        input.value = _cmdHistory[_cmdHistIdx];
      } else {
        _cmdHistIdx = -1;
        input.value = '';
      }
    } else {
      _cmdHistIdx = -1;  // qualquer outra tecla reseta o índice
    }
  }

  async function runCoderCmd() {
    const cmd = document.getElementById('coder-cmd').value.trim();
    if (!cmd) return;
    _saveCmdHistory(cmd);
    document.getElementById('coder-cmd').value = '';
    const trace = document.getElementById('coder-trace');
    const head = document.createElement('div');
    head.style.cssText = 'padding:4px 0;color:#5eead4;font-family:monospace;font-size:11px';
    head.textContent = '$ ' + cmd;
    trace.appendChild(head);
    const out = document.createElement('pre');
    out.style.cssText = 'margin:2px 0 8px;padding:8px 10px;background:#08080b;border:1px solid #1c1c24;border-left:2px solid #5eead4;border-radius:6px;font-size:10.5px;line-height:1.35;max-height:240px;overflow:auto;white-space:pre-wrap;color:#9aa';
    trace.appendChild(out); trace.scrollTop = trace.scrollHeight;

    // #9 WebSocket bidirecional — permite Ctrl+C futuro; fallback SSE se WS falhar
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsOk = false;
    try {
      await new Promise((resolve, reject) => {
        const ws = new WebSocket(`${wsProto}//${location.host}/ws/coder/exec`);
        ws.onopen = () => { wsOk = true; ws.send(JSON.stringify({cmd})); };
        ws.onmessage = (e) => {
          const d = JSON.parse(e.data);
          if (d.type === 'line') {
            out.textContent += (out.textContent?'\n':'') + d.content;
            trace.scrollTop = trace.scrollHeight;
          } else if (d.type === 'done') {
            if (!d.ok) out.style.borderLeftColor = '#f87171';
            ws.close(); resolve();
          } else if (d.type === 'error') {
            out.textContent += '\n✗ ' + (d.message||'erro'); ws.close(); resolve();
          }
        };
        ws.onerror = () => { if (!wsOk) reject(new Error('ws_failed')); else resolve(); };
        ws.onclose = () => resolve();
      });
    } catch {
      // Fallback SSE (compatibilidade com proxies que bloqueiam WS)
      const resp = await fetch('/api/coder/exec', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({cmd})});
      const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf='';
      while (true) {
        const {done, value} = await reader.read(); if (done) break;
        buf += dec.decode(value, {stream:true});
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const p of parts) {
          if (!p.startsWith('data: ')) continue;
          const d = JSON.parse(p.slice(6));
          if (d.type==='cmd_line') { out.textContent+=(out.textContent?'\n':'')+d.content; trace.scrollTop=trace.scrollHeight; }
          else if (d.type==='step'&&d.icon==='✗') out.style.borderLeftColor='#f87171';
        }
      }
    }
    refreshCoderTree();
  }

  async function renameCoderFile(path) {
    const dst = prompt('Novo caminho/nome para:\n' + path, path);
    if (!dst || dst === path) return;
    try {
      const r = await fetch('/api/coder/move', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({src:path, dst})}).then(r=>r.json());
      const ov = document.getElementById('coder-fileview'); if (ov) ov.remove();
      if (!r.ok) alert(r.message || 'Falha ao renomear');
      refreshCoderTree();
    } catch { alert('Falha ao renomear'); }
  }

  async function deleteCoderFile(path) {
    if (!confirm('Apagar ' + path + '? (reversível pelo histórico de Mudanças)')) return;
    try {
      const r = await fetch('/api/coder/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})}).then(r=>r.json());
      const ov = document.getElementById('coder-fileview'); if (ov) ov.remove();
      if (!r.ok) alert(r.message || 'Falha ao apagar');
      refreshCoderTree();
    } catch { alert('Falha ao apagar'); }
  }

  async function runCoderReplace() {
    const find = document.getElementById('coder-find').value;
    const rep = document.getElementById('coder-rep').value;
    if (!find) { alert('Informe o texto a buscar'); return; }
    if (!confirm(`Substituir "${find}" por "${rep}" em TODOS os arquivos do workspace? (reversível)`)) return;
    try {
      const r = await fetch('/api/coder/replace', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({find, replace: rep})}).then(r=>r.json());
      if (r.ok) {
        alert(`✓ ${r.count} ocorrência(s) em ${r.files_changed} arquivo(s).`);
        document.getElementById('coder-find').value=''; document.getElementById('coder-rep').value='';
        refreshCoderTree();
      } else alert('Erro: ' + (r.error||''));
    } catch { alert('Falha na substituição'); }
  }

  // ── Coder V2: viewer com syntax highlighting e preview HTML ao vivo ──────────
  const _LANG_EXT = {
    '.py':'python','.js':'javascript','.mjs':'javascript','.ts':'typescript',
    '.tsx':'typescript','.jsx':'javascript','.html':'html','.htm':'html',
    '.css':'css','.scss':'scss','.json':'json','.yaml':'yaml','.yml':'yaml',
    '.toml':'toml','.sql':'sql','.sh':'bash','.bash':'bash','.zsh':'bash',
    '.go':'go','.rs':'rust','.java':'java','.kt':'kotlin',
    '.c':'c','.cpp':'cpp','.h':'c','.cs':'csharp','.rb':'ruby',
    '.php':'php','.md':'markdown','.tf':'hcl','.dockerfile':'dockerfile',
  };
  function _detectLang(path) {
    const base = (path||'').toLowerCase().split('/').pop();
    if (base === 'dockerfile') return 'dockerfile';
    if (base === 'makefile') return 'makefile';
    const dot = base.lastIndexOf('.');
    return dot >= 0 ? (_LANG_EXT[base.slice(dot)] || '') : '';
  }

  async function viewCoderFile(path) {
    try {
      const d = await fetch('/api/coder/read?path=' + encodeURIComponent(path)).then(r=>r.json());
      const content = d.content || '';
      const lang = _detectLang(path);
      const isHtml = lang === 'html';
      const lines = content.split('\n').length;
      const kb = (new TextEncoder().encode(content).length / 1024).toFixed(1);

      let ov = document.getElementById('coder-fileview');
      if (!ov) {
        ov = document.createElement('div'); ov.id = 'coder-fileview';
        ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:210;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(3px)';
        ov.onclick = e => { if (e.target === ov) ov.remove(); };
        document.body.appendChild(ov);
      }

      const w = isHtml ? 'min(1140px,97vw)' : 'min(880px,95vw)';
      ov.innerHTML = `
        <div style="background:#0b0b0f;border:1px solid #23232c;border-radius:12px;width:${w};height:min(700px,90vh);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px #000c">
          <div style="display:flex;align-items:center;gap:7px;padding:9px 14px;border-bottom:1px solid #16161c;flex-shrink:0;background:#0e0e13">
            <span style="color:#5eead4;font-size:12px;font-family:monospace;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">📄 ${escHtml(path)}</span>
            ${lang ? `<span style="font-size:10px;padding:2px 7px;border-radius:99px;background:#0a1a10;color:#4ade80;border:1px solid #1a3a1a;flex-shrink:0">${lang}</span>` : ''}
            <span style="font-size:10px;color:#444;flex-shrink:0">${lines} linhas · ${kb} KB</span>
            <button id="cfv-copy" onclick="_cfvCopy()" title="Copiar conteúdo" style="background:#16161d;border:1px solid #2a2a33;color:#9aa;border-radius:6px;padding:3px 9px;cursor:pointer;font-size:11px;flex-shrink:0">📋</button>
            <button onclick="openInVSCode('${escHtml(path)}')" title="Abrir no VS Code" style="background:#0e1c2e;border:1px solid #1e3a5b;color:#4ea1ea;border-radius:6px;padding:3px 9px;cursor:pointer;font-size:11px;flex-shrink:0">⧉</button>
            <button onclick="renameCoderFile('${escHtml(path)}')" title="Renomear" style="background:#16161d;border:1px solid #2a2a33;color:#9aa;border-radius:6px;padding:3px 8px;cursor:pointer;font-size:11px;flex-shrink:0">✏️</button>
            <button onclick="deleteCoderFile('${escHtml(path)}')" title="Apagar" style="background:#2a1414;border:1px solid #5a2a2a;color:#f87171;border-radius:6px;padding:3px 8px;cursor:pointer;font-size:11px;flex-shrink:0">🗑️</button>
            <button onclick="document.getElementById('coder-fileview').remove()" style="background:#16161d;border:1px solid #2a2a33;color:#888;border-radius:6px;padding:3px 8px;cursor:pointer;font-size:11px;flex-shrink:0">✕</button>
          </div>
          <div style="flex:1;display:flex;min-height:0">
            <div style="flex:1;overflow:auto;min-width:0;background:#08080b">
              <pre style="margin:0;padding:14px 12px;"><code id="cfv-code" class="${lang ? 'language-'+lang : ''}" style="font-family:ui-monospace,SFMono-Regular,monospace;font-size:11.5px;line-height:1.55;white-space:pre;background:transparent"></code></pre>
            </div>
            ${isHtml ? `<div style="flex:1;border-left:2px solid #1a3a1a;display:flex;flex-direction:column;min-width:0">
              <div style="padding:5px 12px;font-size:10px;color:#4ade80;background:#0a150a;border-bottom:1px solid #1a3a1a;flex-shrink:0;font-weight:600;letter-spacing:.5px">⚡ PREVIEW AO VIVO</div>
              <iframe id="cfv-iframe" sandbox="allow-scripts allow-same-origin" style="flex:1;border:none;background:#fff;width:100%"></iframe>
            </div>` : ''}
          </div>
        </div>`;

      // Syntax highlight
      const codeEl = document.getElementById('cfv-code');
      codeEl.textContent = content;
      if (lang && hljs.getLanguage && hljs.getLanguage(lang)) {
        hljs.highlightElement(codeEl);
      }
      // #5 Números de linha após highlight
      addLineNumbers(document.getElementById('cfv-pre'));

      // Preview HTML ao vivo
      if (isHtml) {
        document.getElementById('cfv-iframe').srcdoc = content;
      }

      // Copy handler
      window._cfvContent = content;
      window._cfvCopy = () => {
        navigator.clipboard.writeText(window._cfvContent).catch(()=>{});
        const btn = document.getElementById('cfv-copy');
        if (!btn) return;
        const orig = btn.textContent;
        btn.textContent = '✓';
        setTimeout(() => btn.textContent = orig, 1500);
      };

    } catch(e) { alert('Falha ao ler arquivo: ' + e.message); }
  }

  async function openInVSCode(path) {
    // path vazio = abre a pasta-raiz do workspace; 'arquivo:linha' posiciona o cursor.
    try {
      const r = await fetch('/api/coder/vscode', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: path || ''})}).then(r=>r.json());
      if (r.ok) showIngestToast(`⧉ Abrindo no VS Code: <b>${escHtml(path || 'workspace')}</b>`);
      else alert('VS Code: ' + (r.error || 'falha ao abrir'));
    } catch(e) { alert('Falha ao abrir VS Code: ' + e.message); }
  }

  async function setCoderWorkspace() {
    const path = document.getElementById('coder-ws-path').value.trim();
    if (!path) return;
    if (!confirm(`Apontar o A.P.O.L.O. Coder para:\n${path}\n\nEle poderá ler, escrever e rodar comandos nessa pasta.`)) return;
    const r = await fetch('/api/coder/workspace', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})}).then(r=>r.json());
    if (r.ok) { refreshCoderTree(); }
    else alert('Erro: ' + (r.error || 'falha'));
  }

  let browseCurrent = '';
  async function openCoderBrowse() {
    document.getElementById('coder-browse').classList.add('show');
    const start = document.getElementById('coder-ws-path').value.trim();
    await loadBrowse(start);
  }
  function closeCoderBrowse() {
    document.getElementById('coder-browse').classList.remove('show');
  }
  function browseRow(icon, label, color, onClick) {
    // Cria a linha via DOM (sem interpolar o caminho em string — seguro com '\' do Windows).
    const row = document.createElement('div');
    row.className = 'browse-row';
    row.innerHTML = `<span>${icon}</span><span${color?` style="color:${color}"`:''}>${escHtml(label)}</span>` + (onClick && icon==='📁' ? '<span class="chev">›</span>' : '');
    if (onClick) row.addEventListener('click', onClick);
    return row;
  }
  async function loadBrowse(path) {
    const list = document.getElementById('browse-list');
    list.innerHTML = '<div style="padding:14px;color:#555;font-size:12px">Carregando…</div>';
    try {
      const d = await fetch('/api/coder/browse?path=' + encodeURIComponent(path || '')).then(r=>r.json());
      browseCurrent = d.current || '';
      document.getElementById('browse-cur').textContent = browseCurrent || '—';
      list.innerHTML = '';
      if (!d.ok) { list.innerHTML = `<div style="padding:14px;color:#f87171;font-size:12px">${escHtml(d.error||'erro')}</div>`; return; }
      if (d.parent) list.appendChild(browseRow('⬆️', '.. (voltar)', '#888', () => loadBrowse(d.parent)));
      if (!d.dirs.length && !d.parent) list.insertAdjacentHTML('beforeend', '<div style="padding:14px;color:#666;font-size:12px">(sem subpastas)</div>');
      for (const dir of d.dirs) list.appendChild(browseRow('📁', dir.name, '', () => loadBrowse(dir.path)));
    } catch(e) {
      list.innerHTML = `<div style="padding:14px;color:#f87171;font-size:12px">Falha: ${escHtml(e.message)}</div>`;
    }
  }
  async function pickCoderBrowse() {
    if (!browseCurrent) return;
    document.getElementById('coder-ws-path').value = browseCurrent;
    closeCoderBrowse();
    await setCoderWorkspace();
  }

  async function coderSelfImprove() {
    if (!confirm('Automelhoria em CÓPIA SEGURA?\n\nO A.P.O.L.O. vai trabalhar numa cópia isolada do próprio código. O projeto ao vivo NÃO é tocado — depois você revisa o diff e decide aplicar ou descartar.')) return;
    showIngestToast('🧪 Criando cópia isolada do projeto...');
    const r = await fetch('/api/coder/sandbox', {method:'POST'}).then(r=>r.json());
    if (r.ok) {
      document.getElementById('coder-ws-path').value = r.root || '';
      setCoderSmart(true);  // automelhoria exige o 14b — o modelo leve destrói o código
      refreshCoderTree();
      document.getElementById('coder-review-btn').style.display = '';
      const task = document.getElementById('coder-task');
      if (task && !task.value.trim()) {
        task.value = 'Leia A.P.O.L.O._Code.md e siga a doutrina. Rode a suíte de testes (python -m pytest -q), analise o código e proponha + implemente UMA melhoria coesa (robustez, performance ou qualidade), provando com testes e atualizando o README.';
      }
      showIngestToast('🧪 Cópia segura pronta (14b + guarda de regressão). Trabalhe e depois clique em "Revisar cópia".');
    } else {
      alert('Erro: ' + (r.error || 'falha'));
    }
  }

  async function reviewSandbox() {
    const r = await fetch('/api/coder/sandbox/diff').then(r=>r.json());
    if (!r.ok) { alert(r.error || 'Nenhuma cópia ativa'); return; }
    let ov = document.getElementById('sandbox-review');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'sandbox-review';
      ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:230;display:flex;align-items:center;justify-content:center';
      ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
      document.body.appendChild(ov);
    }
    const icon = (s) => s === 'added' ? '🟢' : s === 'deleted' ? '🔴' : '🟡';
    const rows = (r.changes || []).map(c =>
      `<div class="browse-row" onclick="viewSandboxDiff('${escHtml(c.path)}')"><span>${icon(c.status)}</span><span>${escHtml(c.path)}</span><span class="chev" style="color:#666">${c.status}</span></div>`).join('')
      || '<div style="padding:16px;color:#888;font-size:12px">Nenhuma mudança na cópia ainda.</div>';
    ov.innerHTML = `<div class="browse-card" style="width:min(680px,95vw);height:min(620px,88vh)">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="margin:0;font-size:14px;color:#eee">🧪 Revisar cópia — ${(r.changes||[]).length} mudança(s)</h3>
        <button class="coder-btn" onclick="document.getElementById('sandbox-review').remove()">✕</button>
      </div>
      <p style="color:#888;font-size:11px;margin:8px 0">Clique num arquivo para ver o diff. Aplicar copia as mudanças para o projeto real.</p>
      <div class="browse-list">${rows}</div>
      <div style="display:flex;gap:8px;margin-top:12px;justify-content:flex-end">
        <button class="coder-btn" onclick="discardSandbox()" style="border-color:#5a2a2a;color:#f87171">🗑️ Descartar cópia</button>
        <button class="coder-btn go" onclick="applySandbox()">✅ Aplicar ao projeto</button>
      </div>
    </div>`;
  }

  async function viewSandboxDiff(path) {
    const r = await fetch('/api/coder/sandbox/file?path=' + encodeURIComponent(path)).then(r=>r.json());
    if (!r.ok) return;
    let ov = document.getElementById('coder-fileview');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'coder-fileview';
      ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:240;display:flex;align-items:center;justify-content:center';
      ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
      document.body.appendChild(ov);
    }
    ov.innerHTML = `<div style="background:#0b0b0f;border:1px solid #23232c;border-radius:12px;width:min(820px,94vw);height:min(640px,88vh);display:flex;flex-direction:column;padding:14px 16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span style="color:#5eead4;font-size:13px">📝 ${escHtml(path)}</span>
        <button class="coder-btn" onclick="document.getElementById('coder-fileview').remove()">✕</button>
      </div>
      <pre style="flex:1;overflow:auto;margin:0;background:#08080b;border:1px solid #1c1c24;border-radius:8px;padding:12px;font-size:11.5px;white-space:pre-wrap"></pre></div>`;
    const pre = ov.querySelector('pre');
    pre.innerHTML = (r.diff || '(sem diff)').split('\n').map(l => {
      const c = l.startsWith('+') && !l.startsWith('+++') ? '#4ade80' : l.startsWith('-') && !l.startsWith('---') ? '#f87171' : '#888';
      return `<span style="color:${c}">${escHtml(l)}</span>`;
    }).join('\n');
  }

  async function applySandbox() {
    if (!confirm('Aplicar TODAS as mudanças da cópia ao projeto real?\n\nIsso altera os arquivos ao vivo. Se o servidor estiver com --reload, ele vai recarregar.')) return;
    const r = await fetch('/api/coder/sandbox/apply', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})}).then(r=>r.json());
    if (r.ok) {
      showIngestToast(`✅ Aplicado: ${r.count} arquivo(s). Reinicie o servidor para carregar as mudanças.`);
      const ov = document.getElementById('sandbox-review'); if (ov) ov.remove();
      await discardSandboxSilent();
    } else alert(r.error || 'Falha ao aplicar');
  }

  async function discardSandboxSilent() {
    await fetch('/api/coder/sandbox/discard', {method:'POST'}).then(r=>r.json()).catch(()=>{});
    document.getElementById('coder-review-btn').style.display = 'none';
    refreshCoderTree();
  }

  async function discardSandbox() {
    if (!confirm('Descartar a cópia e tudo que foi feito nela? O projeto real fica intacto.')) return;
    await discardSandboxSilent();
    const ov = document.getElementById('sandbox-review'); if (ov) ov.remove();
    showIngestToast('🗑️ Cópia descartada. Projeto real intacto.');
  }

  let _coderAbort = null;   // AbortController da tarefa em curso (⏹ Parar)
  async function runCoder() {
    if (_coderAbort) { _coderAbort.abort(); return; }   // 2º clique = parar
    const task = document.getElementById('coder-task').value.trim();
    if (!task) return;
    const btn = document.getElementById('coder-run-btn');
    const trace = document.getElementById('coder-trace');
    _coderAbort = new AbortController();
    btn.textContent = '⏹ Parar';
    btn.title = 'Interromper a tarefa agora';
    trace.innerHTML = '';
    const addStep = (icon, msg) => {
      const div = document.createElement('div');
      div.style.cssText = 'padding:4px 0;border-bottom:1px solid #16161c;white-space:pre-wrap;line-height:1.4';
      div.innerHTML = `<span style="margin-right:6px">${icon}</span>${escHtml(msg)}`;
      trace.appendChild(div); trace.scrollTop = trace.scrollHeight;
    };
    let liveOut = null;
    const addCmdLine = (line) => {
      if (!liveOut) {
        liveOut = document.createElement('pre');
        liveOut.style.cssText = 'margin:3px 0 8px;padding:8px 10px;background:#08080b;border:1px solid #1c1c24;border-left:2px solid #5b9cff;border-radius:6px;font-size:10.5px;line-height:1.35;max-height:200px;overflow:auto;white-space:pre-wrap;color:#9aa';
        trace.appendChild(liveOut);
      }
      liveOut.textContent += (liveOut.textContent ? '\n' : '') + line;
      trace.scrollTop = trace.scrollHeight;
    };
    // ── Testes inteligentes: chip clicável após escrever arquivo ─────────────
    const addTestHint = (srcPath, tests, trace) => {
      const chip = document.createElement('div');
      chip.style.cssText = 'margin:4px 0 6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap';
      const label = document.createElement('span');
      label.style.cssText = 'font-size:10.5px;color:#555';
      label.textContent = `🧪 ${tests.length} teste(s) detectado(s):`;
      chip.appendChild(label);
      tests.forEach(t => {
        const btn = document.createElement('button');
        btn.style.cssText = 'background:#0a1f0a;border:1px solid #1a4a1a;color:#4ade80;padding:2px 9px;border-radius:5px;cursor:pointer;font-size:10.5px;font-family:monospace';
        btn.textContent = t.split('/').pop();
        btn.title = `Rodar ${t}`;
        btn.onclick = () => runTestsFor(srcPath, tests, chip, trace);
        chip.appendChild(btn);
      });
      const runAll = document.createElement('button');
      runAll.style.cssText = 'background:#0a1f0a;border:1px solid #1a4a1a;color:#4ade80;padding:2px 10px;border-radius:5px;cursor:pointer;font-size:10.5px;font-weight:600';
      runAll.textContent = '▶ Rodar todos';
      runAll.onclick = () => runTestsFor(srcPath, tests, chip, trace);
      chip.appendChild(runAll);
      trace.appendChild(chip);
      trace.scrollTop = trace.scrollHeight;
    };

    const runTestsFor = async (srcPath, tests, chip, trace) => {
      chip.innerHTML = '<span style="font-size:10.5px;color:#888">⏳ Rodando testes...</span>';
      try {
        const d = await fetch('/api/coder/test-for', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({path: srcPath}),
        }).then(r => r.json());

        // Resultado compacto
        const total = d.total || 0;
        const passed = d.passed || 0;
        const failed = d.failed || 0;
        const skipped = d.skipped || 0;
        const allPass = failed === 0 && total > 0;

        const res = document.createElement('div');
        res.style.cssText = 'margin:4px 0 8px;padding:8px 10px;border-radius:8px;border:1px solid ' + (allPass ? '#1a3a1a' : '#3a1a1a') + ';background:' + (allPass ? '#0a1a0a' : '#1a0a0a');

        // Sumário
        const sumEl = document.createElement('div');
        sumEl.style.cssText = 'font-size:11px;font-weight:600;margin-bottom:6px';
        if (total === 0) {
          sumEl.style.color = '#888';
          sumEl.textContent = `🧪 ${(d.tests_found||[]).join(', ')} — sem resultados`;
        } else {
          sumEl.style.color = allPass ? '#4ade80' : '#f87171';
          sumEl.textContent = `${allPass ? '✅' : '❌'} ${passed}/${total} passou${failed ? ` · ${failed} falhou` : ''}${skipped ? ` · ${skipped} pulou` : ''}`;
        }
        res.appendChild(sumEl);

        // Lista de testes (máx 20)
        const results = (d.results || []).slice(0, 20);
        results.forEach(r => {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:10px;font-family:monospace;padding:1px 0;color:' +
            (r.status==='passed' ? '#4ade80' : r.status==='skipped' ? '#888' : '#f87171');
          const icon = r.status==='passed' ? '✓' : r.status==='skipped' ? '−' : '✗';
          row.textContent = `${icon} ${r.test}`;
          res.appendChild(row);
        });
        if ((d.results||[]).length > 20) {
          const more = document.createElement('div');
          more.style.cssText = 'font-size:10px;color:#555;margin-top:3px';
          more.textContent = `… +${d.results.length - 20} testes`;
          res.appendChild(more);
        }
        chip.replaceWith(res);
        trace.scrollTop = trace.scrollHeight;
      } catch(e) {
        chip.innerHTML = `<span style="font-size:10.5px;color:#f87171">✗ Falha: ${escHtml(e.message)}</span>`;
      }
    };

    const addPlan = (text) => {
      const card = document.createElement('div');
      card.style.cssText = 'margin:4px 0 10px;padding:10px 12px;background:#0d1a14;border:1px solid #1a3a28;border-left:3px solid #4ade80;border-radius:8px;';
      const steps = (text||'').split('\n').filter(l=>l.trim()).map(l=>`<div style="padding:2px 0;font-size:11.5px;color:#a0dbb8;white-space:pre-wrap">${escHtml(l.trim())}</div>`).join('');
      card.innerHTML = `<div style="font-size:10px;color:#4ade80;letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px;font-weight:700">📋 Plano de execução</div>${steps}`;
      trace.appendChild(card); trace.scrollTop = trace.scrollHeight;
    };
    const addDiff = (path, diffText) => {
      const lines = diffText.split('\n').map(l => {
        let color = '#7a7a85';
        if (l.startsWith('+') && !l.startsWith('+++')) color = '#4ade80';
        else if (l.startsWith('-') && !l.startsWith('---')) color = '#f87171';
        else if (l.startsWith('@@')) color = '#5b9cff';
        return `<span style="color:${color}">${escHtml(l) || ' '}</span>`;
      }).join('\n');
      const pre = document.createElement('pre');
      pre.style.cssText = 'margin:3px 0 8px;padding:8px 10px;background:#0a0a0e;border:1px solid #1c1c24;border-radius:6px;font-size:10.5px;line-height:1.35;overflow-x:auto;white-space:pre';
      pre.innerHTML = lines;
      trace.appendChild(pre); trace.scrollTop = trace.scrollHeight;
    };
    try {
      const resp = await fetch('/api/coder', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({message: task, smart: coderSmart}),
        signal: _coderAbort.signal
      });
      const reader = resp.body.getReader();
      const dec = new TextDecoder(); let buf = '', answer = '';
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {stream:true});
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const p of parts) {
          if (!p.startsWith('data: ')) continue;
          const d = JSON.parse(p.slice(6));
          if (d.type === 'plan') addPlan(d.text);
          else if (d.type === 'step') { addStep(d.icon, d.message); liveOut = null; }
          else if (d.type === 'diff') addDiff(d.path, d.diff);
          else if (d.type === 'test_hint') addTestHint(d.path, d.tests, trace);
          else if (d.type === 'cmd_line') addCmdLine(d.content);
          else if (d.type === 'token') answer += d.content;
          else if (d.type === 'done') answer = d.answer || answer;
          else if (d.type === 'error') addStep('❌', d.message);
        }
      }
      const fin = document.createElement('div');
      fin.style.cssText = 'margin-top:10px;padding:10px;background:#0e2b27;border:1px solid #1e5b52;border-radius:8px;color:#d7fff7;white-space:pre-wrap;line-height:1.5';
      fin.innerHTML = '<b>✅ Concluído</b>\n' + escHtml(answer.trim() || 'Tarefa encerrada — veja o workspace ao lado.');
      trace.appendChild(fin); trace.scrollTop = trace.scrollHeight;
    } catch (e) {
      if (e.name === 'AbortError') addStep('⏹', 'Tarefa interrompida por você. As alterações já feitas estão no histórico (dá para desfazer).');
      else addStep('❌', 'Falha: ' + e.message);
    } finally {
      _coderAbort = null;
      btn.disabled = false; btn.textContent = '▶ Executar'; btn.title = '';
      refreshCoderTree();
    }
  }

  // ── Notificações (autonomia visível) ─────────────────────────
  let notifTimer = null;
  function _relTime(iso) {
    try {
      const s = Math.floor((Date.now() - new Date(iso).getTime())/1000);
      if (s < 60) return 'agora';
      if (s < 3600) return Math.floor(s/60)+'min atrás';
      if (s < 86400) return Math.floor(s/3600)+'h atrás';
      return Math.floor(s/86400)+'d atrás';
    } catch { return ''; }
  }

  async function refreshNotifications() {
    try {
      const d = await fetch('/api/notifications').then(r=>r.json());
      const badge = document.getElementById('bell-badge');
      if (d.unread > 0) { badge.textContent = d.unread > 99 ? '99+' : d.unread; badge.classList.add('show'); }
      else badge.classList.remove('show');
      const list = document.getElementById('notif-list');
      if (!d.items.length) { list.innerHTML = '<div class="notif-empty">Nada por aqui ainda.<br>O A.P.O.L.O. avisa o que fizer sozinho.</div>'; return; }
      // Prioridade (M4 4.3): borda de destaque p/ o que importa; ×N para avisos
      // colapsados (ex.: "📚 Estudei 5 tópicos" em vez de 5 linhas de ruído).
      list.innerHTML = d.items.map(n=>{
        const cnt = (n.count||1) > 1 ? ` <span style="opacity:.55;font-size:11px">×${n.count}</span>` : '';
        const accent = (n.priority||0) >= 3 ? 'border-left:2px solid #fbbf24;padding-left:8px'
                     : (n.priority||0) >= 2 ? 'border-left:2px solid #5b9cff;padding-left:8px' : '';
        return `<div class="notif-item ${n.read?'':'unread'}" style="${accent}">
          ${escHtml(n.message)}${cnt}
          <div class="nt-time">${_relTime(n.created_at)}</div>
        </div>`;
      }).join('');
    } catch {}
  }

  function toggleNotifications(ev) {
    if (ev) ev.stopPropagation();
    const dd = document.getElementById('notif-dropdown');
    const opening = !dd.classList.contains('open');
    dd.classList.toggle('open');
    if (opening) { refreshNotifications(); }
  }

  async function markNotificationsRead() {
    await fetch('/api/notifications/read', {method:'POST'});
    refreshNotifications();
  }

  async function clearNotifications() {
    if (!confirm('Limpar todas as notificações?')) return;
    await fetch('/api/notifications', {method:'DELETE'});
    refreshNotifications();
  }

  function startNotifications() {
    refreshNotifications();
    if (notifTimer) clearInterval(notifTimer);
    notifTimer = setInterval(refreshNotifications, 30000);
  }

  // Fecha o dropdown ao clicar fora.
  document.addEventListener('click', (e) => {
    const dd = document.getElementById('notif-dropdown');
    const bell = document.getElementById('bell-btn');
    if (dd && dd.classList.contains('open') && !dd.contains(e.target) && !bell.contains(e.target))
      dd.classList.remove('open');
  });

  // ── Command palette (Ctrl/Cmd+K) ─────────────────────────────
  const PALETTE_ACTIONS = [
    {icon:'💻', label:'A.P.O.L.O. Coder', fn:()=>openCoder()},
    {icon:'🧠', label:'Mente do A.P.O.L.O.', fn:()=>openMind()},
    {icon:'🗺️', label:'Mapa de Conhecimento', fn:()=>openGraph()},
    {icon:'📚', label:'Base de Conhecimento', fn:()=>openKnowledge()},
    {icon:'🩺', label:'Saúde do Sistema', fn:()=>openHealth()},
    {icon:'🔍', label:'Revisar Código', fn:()=>openReview()},
    {icon:'⏰', label:'Estudos agendados', fn:()=>openSchedules()},
    {icon:'👤', label:'Sobre mim', fn:()=>openProfile()},
    {icon:'🔬', label:'Pesquisa Profunda', fn:()=>activateResearchFromCard()},
    {icon:'📊', label:'Painel de aprendizado', fn:()=>toggleLearnDash()},
    {icon:'🔔', label:'Notificações', fn:()=>toggleNotifications()},
    {icon:'➕', label:'Nova conversa', fn:()=>newChat()},
  ];
  let paletteFiltered = PALETTE_ACTIONS, paletteSel = 0;

  function openPalette() {
    document.getElementById('palette-overlay').style.display = 'flex';
    const inp = document.getElementById('palette-input');
    inp.value = ''; paletteSel = 0; renderPalette(); inp.focus();
  }
  function closePalette() { document.getElementById('palette-overlay').style.display = 'none'; }
  function renderPalette() {
    const q = (document.getElementById('palette-input').value || '').toLowerCase().trim();
    paletteFiltered = PALETTE_ACTIONS.filter(a => !q || a.label.toLowerCase().includes(q));
    if (paletteSel >= paletteFiltered.length) paletteSel = 0;
    document.getElementById('palette-list').innerHTML = paletteFiltered.map((a, i) =>
      `<div class="palette-item" onclick="runPalette(${i})" onmouseover="paletteSel=${i};paletteHi()"
         style="display:flex;gap:10px;padding:10px 16px;cursor:pointer;font-size:13px;color:#ccc;${i===paletteSel?'background:#1a1a24':''}">
         <span>${a.icon}</span><span>${escHtml(a.label)}</span></div>`
    ).join('') || '<div style="padding:14px 16px;color:#555;font-size:12px">Nada encontrado</div>';
  }
  function paletteHi() {
    [...document.querySelectorAll('#palette-list .palette-item')].forEach((el,i)=>
      el.style.background = i===paletteSel ? '#1a1a24' : 'none');
  }
  function runPalette(i) {
    const a = paletteFiltered[i]; if (!a) return;
    closePalette();
    try { a.fn(); } catch (e) {}
  }
  function paletteKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); paletteSel = Math.min(paletteSel+1, paletteFiltered.length-1); paletteHi(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); paletteSel = Math.max(paletteSel-1, 0); paletteHi(); }
    else if (e.key === 'Enter') { e.preventDefault(); runPalette(paletteSel); }
    else if (e.key === 'Escape') { closePalette(); }
  }
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      const ov = document.getElementById('palette-overlay');
      if (ov.style.display === 'flex') closePalette(); else openPalette();
    }
  });

  // Esc fecha o painel/overlay aberto (UX consistente em todos os painéis).
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const pal = document.getElementById('palette-overlay');
    if (pal && pal.style.display === 'flex') { closePalette(); return; }
    const dd = document.getElementById('notif-dropdown');
    if (dd && dd.classList.contains('open')) { dd.classList.remove('open'); return; }
    // Navegador de pastas do Coder tem prioridade sobre fechar a aba
    const brw = document.getElementById('coder-browse');
    if (brw && brw.classList.contains('show')) { closeCoderBrowse(); return; }
    // Coder é uma aba docada (classe .show) — Esc volta ao chat
    if (isCoderOpen()) { closeCoder(); return; }
    // Overlays baseados em display:flex/none
    const byDisplay = {graph:closeGraph, schedules:closeSchedules, health:closeHealth};
    for (const [k, fn] of Object.entries(byDisplay)) {
      const el = document.getElementById(k + '-overlay');
      if (el && el.style.display === 'flex') { fn(); return; }
    }
    // Overlays baseados na classe .open
    const byClass = {knowledge:closeKnowledge, mind:closeMind, profile:closeProfile, review:closeReview};
    for (const [k, fn] of Object.entries(byClass)) {
      const el = document.getElementById(k + '-overlay');
      if (el && el.classList.contains('open')) { fn(); return; }
    }
  });

  // ── Mapa de conhecimento (SVG radial) ────────────────────────
  function openGraph() { document.getElementById('graph-overlay').style.display='flex'; loadGraph(); }
  function closeGraph() { document.getElementById('graph-overlay').style.display='none'; }

  async function loadGraph() {
    const canvas = document.getElementById('graph-canvas');
    canvas.innerHTML = '<div id="graph-loading" style="color:#555;text-align:center;margin-top:40px">Desenhando o mapa…</div>';
    try {
      const g = await fetch('/api/knowledge/graph').then(r=>r.json());
      const sectors = (g.nodes||[]).filter(n=>n.type==='sector');
      document.getElementById('graph-sub').textContent = sectors.length ? `${sectors.length} setores` : '';
      if (!sectors.length) { canvas.innerHTML = '<div style="color:#555;text-align:center;margin-top:40px">Ainda sem conhecimento suficiente para o mapa. Ative o aprendizado.</div>'; return; }

      const W = canvas.clientWidth || 840, H = canvas.clientHeight || 560;
      const cx = W/2, cy = H/2;
      const Rsec = Math.min(W, H) * 0.30;   // raio dos setores
      const Rtop = Math.min(W, H) * 0.46;   // raio dos tópicos
      const maxCount = Math.max(...sectors.map(s=>s.count||1));
      const palette = ['#5b9cff','#4ade80','#facc15','#f472b6','#a78bfa','#fb923c','#22d3ee','#34d399','#e879f9','#f87171'];

      let lines = '', nodes = '';
      // posição de cada setor
      const pos = {};
      sectors.forEach((s, i) => {
        const ang = (i / sectors.length) * 2 * Math.PI - Math.PI/2;
        const x = cx + Rsec * Math.cos(ang), y = cy + Rsec * Math.sin(ang);
        pos[s.id] = {x, y, color: palette[i % palette.length], ang};
      });
      // arestas centro→setor
      sectors.forEach(s => {
        const p = pos[s.id];
        lines += `<line x1="${cx}" y1="${cy}" x2="${p.x}" y2="${p.y}" stroke="${p.color}" stroke-opacity="0.35" stroke-width="1.5"/>`;
      });
      // tópicos (folhas) por setor
      (g.edges||[]).forEach(e => {
        if (!e.source.startsWith('sec::')) return;
        const sp = pos[e.source]; if (!sp) return;
        const node = g.nodes.find(n=>n.id===e.target); if (!node) return;
        // espalha as folhas radialmente para fora do setor
        const idx = parseInt((e.target.split('::t')[1]||'0'),10);
        const spread = (idx - 1.5) * 0.28;
        const ang = sp.ang + spread;
        const x = cx + Rtop * Math.cos(ang), y = cy + Rtop * Math.sin(ang);
        lines += `<line x1="${sp.x}" y1="${sp.y}" x2="${x}" y2="${y}" stroke="${sp.color}" stroke-opacity="0.18" stroke-width="1"/>`;
        const tx = x < cx ? x - 4 : x + 4, anchor = x < cx ? 'end' : 'start';
        nodes += `<circle cx="${x}" cy="${y}" r="3" fill="${sp.color}" fill-opacity="0.7"/>
                  <text x="${tx}" y="${y+3}" text-anchor="${anchor}" font-size="9" fill="#8a8a93">${escHtml(node.label.slice(0,26))}</text>`;
      });
      // nós de setor (tamanho ∝ count)
      sectors.forEach(s => {
        const p = pos[s.id];
        const r = 10 + 14 * ((s.count||1)/maxCount);
        const tx = p.x < cx ? p.x : p.x, anchor='middle';
        nodes += `<circle cx="${p.x}" cy="${p.y}" r="${r}" fill="${p.color}" fill-opacity="0.18" stroke="${p.color}" stroke-width="1.5" style="cursor:pointer" onclick="graphPickSector('${s.sector}')"/>
                  <text x="${p.x}" y="${p.y - r - 5}" text-anchor="${anchor}" font-size="11" fill="#ddd" style="cursor:pointer" onclick="graphPickSector('${s.sector}')">${escHtml(s.label)}</text>
                  <text x="${p.x}" y="${p.y+4}" text-anchor="middle" font-size="10" fill="${p.color}">${s.count}</text>`;
      });
      // núcleo
      nodes += `<circle cx="${cx}" cy="${cy}" r="26" fill="#1a1505" stroke="var(--sun)" stroke-width="2"/>
                <text x="${cx}" y="${cy+4}" text-anchor="middle" font-size="13" fill="var(--sun)" font-weight="700">☀️</text>`;

      canvas.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="100%">${lines}${nodes}</svg>`;
    } catch (e) {
      canvas.innerHTML = '<div style="color:#f87171;text-align:center;margin-top:40px">Falha ao carregar o mapa</div>';
    }
  }

  function graphPickSector(sector) {
    closeGraph();
    if (typeof openKnowledge === 'function') {
      openKnowledge();
      setTimeout(() => {
        const sel = document.getElementById('kp-sector');
        if (sel) { sel.value = sector; if (typeof renderKnowledgeItems==='function') renderKnowledgeItems(); }
      }, 300);
    }
  }

  // ── Estudos agendados ────────────────────────────────────────
  function openSchedules() { document.getElementById('schedules-overlay').style.display='flex'; loadSchedules(); }
  function closeSchedules() { document.getElementById('schedules-overlay').style.display='none'; }

  async function loadSchedules() {
    const el = document.getElementById('sch-list');
    try {
      const list = await fetch('/api/schedules').then(r=>r.json());
      if (!list.length) { el.innerHTML = '<div style="color:#555;padding:8px 0">Nenhum estudo agendado ainda.</div>'; return; }
      el.innerHTML = list.map(s=>`
        <div style="display:flex;align-items:center;gap:10px;padding:9px 11px;background:#15151b;border:1px solid #23232c;border-radius:8px;margin-bottom:7px;${s.enabled?'':'opacity:.5'}">
          <span style="color:var(--sun);font-weight:600;font-variant-numeric:tabular-nums">${escHtml(s.time_of_day)}</span>
          <span style="flex:1">${escHtml(s.topic)}</span>
          ${s.last_run?`<span style="font-size:9px;color:#555" title="Último estudo">✓ ${escHtml(s.last_run.slice(0,10))}</span>`:''}
          <span onclick="toggleSchedule(${s.id})" title="${s.enabled?'Pausar':'Ativar'}" style="cursor:pointer">${s.enabled?'⏸️':'▶️'}</span>
          <span onclick="deleteSchedule(${s.id})" title="Remover" style="cursor:pointer;color:#f87171">🗑️</span>
        </div>`).join('');
    } catch { el.innerHTML='<span style="color:#f87171">Falha ao carregar</span>'; }
  }

  async function addSchedule() {
    const topic = document.getElementById('sch-topic').value.trim();
    const time = document.getElementById('sch-time').value;
    if (topic.length < 3) { alert('Tópico muito curto'); return; }
    const r = await fetch('/api/schedules', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({topic, time_of_day: time})
    }).then(r=>r.json());
    if (r.ok) { document.getElementById('sch-topic').value=''; loadSchedules(); }
    else alert('Erro: ' + (r.error || 'falha'));
  }

  async function deleteSchedule(id) {
    if (!confirm('Remover este estudo agendado?')) return;
    await fetch('/api/schedules/'+id, {method:'DELETE'});
    loadSchedules();
  }

  async function toggleSchedule(id) {
    await fetch('/api/schedules/'+id+'/toggle', {method:'POST'});
    loadSchedules();
  }

  // ── Painel de Saúde ──────────────────────────────────────────
  function openHealth() { document.getElementById('health-overlay').style.display='flex'; loadHealth(); }
  function closeHealth() { document.getElementById('health-overlay').style.display='none'; }

  // ── Painel de Permissões (consentimento de agência — M6) ─────
  function openPermissions() { document.getElementById('perm-overlay').style.display='flex'; loadPermissions(); }
  function closePermissions() { document.getElementById('perm-overlay').style.display='none'; }

  // ── Ações reversíveis (M10 10.1): preview → confirmar → desfazer ──
  function openActions() { document.getElementById('actions-overlay').style.display='flex'; loadActionsLedger(); loadRoutines(); }
  function closeActions() { document.getElementById('actions-overlay').style.display='none'; }

  async function previewWriteAction() {
    const path = document.getElementById('act-path').value.trim();
    const content = document.getElementById('act-content').value;
    const box = document.getElementById('act-preview');
    const confirmBtn = document.getElementById('act-confirm-btn');
    confirmBtn.disabled = true; confirmBtn.style.opacity = '.4';
    if (!path) { box.innerHTML = '<span style="color:#f87171">Informe o caminho do arquivo.</span>'; return; }
    box.innerHTML = '<span style="color:#666">Gerando prévia…</span>';
    try {
      const d = await fetch('/api/actions/preview', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({kind:'files.write', args:{path, content}})}).then(r=>r.json());
      if (!d.ok) { box.innerHTML = `<span style="color:#f87171">${escHtml(d.error||'não foi possível pré-visualizar')}</span>`; return; }
      const p = d.preview;
      const verb = p.action === 'overwrite' ? '✏️ Sobrescrever' : '🆕 Criar';
      box.innerHTML = `<div style="background:#08080b;border:1px solid #1c1c24;border-radius:8px;padding:10px;font-size:11.5px">
        <div style="color:${p.action==='overwrite'?'#fbbf24':'#4ade80'};margin-bottom:6px">${verb} — <code style="color:#bbb">${escHtml(p.path)}</code></div>
        ${p.exists ? `<div style="color:#777;margin-bottom:2px">Antes (${p.old_bytes} bytes):</div><pre style="margin:0 0 8px;white-space:pre-wrap;color:#a88;max-height:120px;overflow:auto">${escHtml(p.old_preview)||'<vazio>'}</pre>` : ''}
        <div style="color:#777;margin-bottom:2px">Depois (${p.new_bytes} bytes):</div>
        <pre style="margin:0;white-space:pre-wrap;color:#8b8;max-height:160px;overflow:auto">${escHtml(p.new_preview)||'<vazio>'}</pre>
      </div>`;
      confirmBtn.disabled = false; confirmBtn.style.opacity = '1';
    } catch(e) { box.innerHTML = `<span style="color:#f87171">Erro: ${escHtml(e.message)}</span>`; }
  }

  async function confirmWriteAction() {
    const path = document.getElementById('act-path').value.trim();
    const content = document.getElementById('act-content').value;
    const box = document.getElementById('act-preview');
    const btn = document.getElementById('act-confirm-btn');
    btn.disabled = true; btn.style.opacity = '.4';
    try {
      const d = await fetch('/api/actions/confirm', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({kind:'files.write', args:{path, content}})}).then(r=>r.json());
      if (!d.ok) { box.innerHTML = `<span style="color:#f87171">${escHtml(d.error||'falhou')}</span>`; return; }
      box.innerHTML = `<span style="color:#4ade80">✓ ${escHtml(d.description||'Escrito')} — pode desfazer abaixo.</span>`;
      document.getElementById('act-path').value = ''; document.getElementById('act-content').value = '';
      loadActionsLedger();
    } catch(e) { box.innerHTML = `<span style="color:#f87171">Erro: ${escHtml(e.message)}</span>`; }
  }

  async function loadActionsLedger() {
    const el = document.getElementById('act-ledger');
    try {
      const d = await fetch('/api/actions/undo?limit=30').then(r=>r.json());
      if (!d.items || !d.items.length) { el.innerHTML = '<div style="color:#555;padding:6px 0">Nenhuma ação ainda.</div>'; return; }
      el.innerHTML = d.items.map(it => {
        const when = it.created_at ? new Date(it.created_at).toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
        const undoBtn = it.undone
          ? '<span style="color:#555;font-size:11px">↩️ desfeito</span>'
          : `<button onclick="undoLedgerItem(${it.id})" style="background:#2a1010;border:1px solid #5a1a1a;color:#f87171;padding:3px 9px;border-radius:6px;cursor:pointer;font-size:11px">↩️ Desfazer</button>`;
        return `<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid #16161c">
          <div><div style="color:${it.undone?'#666':'#ddd'}">${escHtml(it.description||it.kind)}</div>
          <div style="color:#555;font-size:10.5px">${escHtml(it.kind)} · ${when}</div></div>${undoBtn}</div>`;
      }).join('');
    } catch(e) { el.innerHTML = `<span style="color:#f87171">Erro ao carregar: ${escHtml(e.message)}</span>`; }
  }

  async function undoLedgerItem(id) {
    try {
      const d = await fetch('/api/actions/undo', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({undo_id:id})}).then(r=>r.json());
      if (!d.ok) alert(d.error || 'não foi possível desfazer');
    } catch(e) { alert('Erro: ' + e.message); }
    loadActionsLedger();
  }

  // ── Rotinas automatizadas (M10 10.2) ──
  async function loadRoutines() {
    const el = document.getElementById('rot-list');
    if (!el) return;
    try {
      const d = await fetch('/api/routines').then(r=>r.json());
      if (!d.routines || !d.routines.length) { el.innerHTML = '<div style="color:#555;padding:4px 0">Nenhuma rotina ainda.</div>'; return; }
      el.innerHTML = d.routines.map(r => {
        const last = r.last_run ? new Date(r.last_run).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : 'nunca';
        const onoff = r.enabled
          ? `<button onclick="toggleRoutine(${r.id})" title="Pausar" style="background:#0a1f0a;border:1px solid #1a4a1a;color:#4ade80;padding:2px 8px;border-radius:6px;cursor:pointer;font-size:11px">ativa</button>`
          : `<button onclick="toggleRoutine(${r.id})" title="Ativar" style="background:#1a1a22;border:1px solid #2a2a33;color:#888;padding:2px 8px;border-radius:6px;cursor:pointer;font-size:11px">pausada</button>`;
        return `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 0;border-bottom:1px solid #16161c">
          <div><div style="color:#ddd">${escHtml(r.name)}</div>
          <div style="color:#555;font-size:10.5px">${escHtml(r.schedule_human||'')} · último: ${last}</div></div>
          <div style="display:flex;gap:5px;align-items:center">${onoff}
            <button onclick="runRoutineNow(${r.id})" title="Rodar agora" style="background:#0a1a2a;border:1px solid #1a3a5a;color:#5b9cff;padding:2px 8px;border-radius:6px;cursor:pointer;font-size:11px">▶</button>
            <button onclick="deleteRoutine(${r.id})" title="Remover" style="background:#2a1010;border:1px solid #5a1a1a;color:#f87171;padding:2px 8px;border-radius:6px;cursor:pointer;font-size:11px">✕</button>
          </div></div>`;
      }).join('');
    } catch(e) { el.innerHTML = `<span style="color:#f87171">Erro: ${escHtml(e.message)}</span>`; }
  }

  async function createRoutine() {
    const name = document.getElementById('rot-name').value.trim() || 'Resumo da semana';
    const weekday = parseInt(document.getElementById('rot-weekday').value, 10);
    const time = document.getElementById('rot-time').value || '18:00';
    const path = document.getElementById('rot-path').value.trim();
    if (!path) { alert('Informe o caminho do arquivo onde salvar o resumo.'); return; }
    try {
      const d = await fetch('/api/routines', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name, kind:'weekly_digest', freq:'weekly', weekday, time_of_day:time, config:{path}})}).then(r=>r.json());
      if (!d.ok) { alert(d.error || 'não foi possível criar'); return; }
      document.getElementById('rot-name').value = ''; document.getElementById('rot-path').value = '';
      loadRoutines();
    } catch(e) { alert('Erro: ' + e.message); }
  }

  async function toggleRoutine(id) {
    try { await fetch(`/api/routines/${id}/toggle`, {method:'POST'}); } catch {}
    loadRoutines();
  }

  async function runRoutineNow(id) {
    try {
      const d = await fetch(`/api/routines/${id}/run`, {method:'POST'}).then(r=>r.json());
      if (!d.ok) alert(d.error || 'não foi possível rodar');
    } catch(e) { alert('Erro: ' + e.message); }
    loadRoutines(); loadActionsLedger();
  }

  async function deleteRoutine(id) {
    if (!confirm('Remover esta rotina?')) return;
    try { await fetch(`/api/routines/${id}`, {method:'DELETE'}); } catch {}
    loadRoutines();
  }

  // Guarda os escopos do último load: caminhos do Windows têm '\' e quebrariam
  // se fossem inlinados no onclick — então o toggle busca a note por escopo aqui.
  let _permScopes = [];

  // Escopos cuja note é um CAMINHO (allowlist): a autorização pede o caminho.
  const _SCOPE_PATH = {
    'files.read':    { icon: '📁', ask: 'Qual pasta o A.P.O.L.O. pode LER? (somente leitura, confinado a ela)\nEx.: C:\\Users\\leore\\Documents\\Notas' },
    'calendar.read': { icon: '📅', ask: 'Caminho do arquivo de agenda .ics que ele pode LER:\nEx.: C:\\Users\\leore\\Documents\\agenda.ics' },
  };

  async function loadPermissions() {
    const body = document.getElementById('perm-body');
    body.textContent = 'Carregando…';
    try {
      const d = await fetch('/api/permissions').then(r=>r.json());
      _permScopes = d.scopes || [];
      if (!_permScopes.length) { body.innerHTML = '<div style="color:#666">Nenhuma capacidade disponível.</div>'; return; }
      body.innerHTML = _permScopes.map(s => {
        // Escopos de caminho mostram a note (pasta/.ics autorizado) + atalho p/ trocar.
        const cfg = _SCOPE_PATH[s.scope];
        const note = (cfg && s.granted && s.note)
          ? `<div style="color:#a78bfa;font-size:10.5px;margin-top:3px;word-break:break-all">${cfg.icon} ${escHtml(s.note)}
               <span onclick="editScopePath('${escHtml(s.scope)}')" style="color:#666;cursor:pointer;margin-left:6px">✎ trocar</span></div>`
          : '';
        return `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 0;border-bottom:1px solid #16161c">
          <div style="min-width:0">
            <div style="color:#e0e0e0"><code style="color:#5b9cff">${escHtml(s.scope)}</code></div>
            <div style="color:#777;font-size:11px">${escHtml(s.label)}</div>
            ${note}
          </div>
          <button onclick="togglePermission('${escHtml(s.scope)}', ${s.granted})"
            style="flex-shrink:0;border:1px solid ${s.granted?'#4ade80':'#2a2a33'};background:${s.granted?'rgba(74,222,128,.12)':'#1a1a22'};color:${s.granted?'#4ade80':'#aaa'};border-radius:7px;padding:4px 12px;cursor:pointer;font-size:11.5px">
            ${s.granted ? '✓ Autorizado' : 'Autorizar'}
          </button>
        </div>`;
      }).join('');
    } catch { body.innerHTML = '<div style="color:#e66">Falha ao carregar as permissões.</div>'; }
  }

  // Grava o grant de um escopo-de-caminho com a note = allowlist (pasta ou .ics).
  async function _grantScopePath(scope, prefill) {
    const cfg = _SCOPE_PATH[scope];
    if (!cfg) return false;
    const val = window.prompt(cfg.ask, prefill || '');
    if (val === null) return false;                     // cancelou
    const path = val.trim();
    if (!path) { showIngestToast('⚠️ Informe um caminho para autorizar.'); return false; }
    await fetch('/api/permissions/grant', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({scope, note: path})});
    showIngestToast(`🔐 Autorizado: ${escHtml(scope)} → ${escHtml(path)}`);
    return true;
  }

  function editScopePath(scope) {
    const cur = (_permScopes.find(x => x.scope === scope) || {}).note || '';
    _grantScopePath(scope, cur).then(ok => { if (ok) loadPermissions(); });
  }

  async function togglePermission(scope, granted) {
    if (granted) {
      try {
        await fetch('/api/permissions/revoke', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({scope})});
        showIngestToast(`🔓 Permissão revogada: ${escHtml(scope)}`);
      } catch {}
      loadPermissions();
      return;
    }
    // Escopos de caminho (files.read/calendar.read) pedem a pasta/arquivo (allowlist).
    if (_SCOPE_PATH[scope]) {
      const ok = await _grantScopePath(scope, (_permScopes.find(x => x.scope === scope) || {}).note || '');
      if (ok) loadPermissions();
      return;
    }
    try {
      await fetch('/api/permissions/grant', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({scope})});
      showIngestToast(`🔐 Permissão concedida: ${escHtml(scope)}`);
    } catch {}
    loadPermissions();
  }

  // ── Painel de Auditoria (o que a IA fez nas últimas 24h) ─────
  function openAudit() { document.getElementById('audit-overlay').style.display='flex'; loadAudit(); }
  function closeAudit() { document.getElementById('audit-overlay').style.display='none'; }

  function _auditWhen(ts) {
    if (!ts) return '';
    const d = new Date(ts), diff = (Date.now() - d.getTime()) / 60000;  // minutos
    if (diff < 1) return 'agora';
    if (diff < 60) return `há ${Math.round(diff)} min`;
    if (diff < 1440) return `há ${Math.round(diff/60)}h`;
    return d.toLocaleString('pt-BR', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'});
  }

  async function loadAudit() {
    const body = document.getElementById('audit-body');
    const sum = document.getElementById('audit-summary');
    body.textContent = 'Carregando…'; sum.innerHTML = '';
    try {
      const d = await fetch('/api/audit?hours=24&limit=100').then(r=>r.json());
      const s = d.summary || {};
      const chips = [
        ['📚', s.learned, 'estudos'], ['💻', s.coder_tasks, 'tarefas'],
        ['⚙️', s.executions, 'execuções'], ['🔔', s.notifications, 'avisos'],
        ['🎯', s.benchmarks, 'autoavaliações'],
      ].filter(([,n]) => n > 0);
      sum.innerHTML = chips.length
        ? chips.map(([ic,n,lbl]) =>
            `<span style="background:#17171d;border:1px solid var(--border);border-radius:20px;padding:3px 10px;font-size:11.5px;color:#ccc">${ic} <b>${n}</b> ${lbl}</span>`).join('')
        : '';
      const ev = d.events || [];
      if (!ev.length) { body.innerHTML = '<div style="color:#666;text-align:center;padding:24px">Nada registrado nas últimas 24h.</div>'; return; }
      body.innerHTML = ev.map(e => {
        const rev = e.reverted ? ' style="opacity:.55"' : '';
        const url = e.url ? ` <a href="${escHtml(e.url)}" target="_blank" rel="noopener" style="color:#5b9cff">↗</a>` : '';
        return `<div${rev} style="display:flex;gap:9px;padding:7px 0;border-bottom:1px solid #16161c">
          <span style="font-size:15px;flex-shrink:0">${e.icon||'•'}</span>
          <div style="min-width:0;flex:1">
            <div style="color:#e0e0e0">${escHtml(e.title)}${url}</div>
            ${e.detail ? `<div style="color:#777;font-size:11px;margin-top:1px">${escHtml(e.detail)}</div>` : ''}
          </div>
          <span style="color:#666;font-size:10.5px;white-space:nowrap;flex-shrink:0">${_auditWhen(e.ts)}</span>
        </div>`;
      }).join('');
    } catch (e) {
      body.innerHTML = '<div style="color:#e66">Falha ao carregar a auditoria.</div>';
    }
  }

  // ── Painel Analytics ─────────────────────────────────────────
  function openAnalytics() {
    document.getElementById('analytics-overlay').classList.add('open');
    lazyLoad('analytics', loadAnalytics);  // #7 só carrega na 1ª abertura
  }
  function closeAnalytics() {
    document.getElementById('analytics-overlay').classList.remove('open');
  }

  function _scoreColor(s) {
    if (s == null) return '#555';
    if (s >= 0.8) return '#4ade80';
    if (s >= 0.6) return '#fbbf24';
    return '#f87171';
  }

  async function loadAnalytics() {
    const body = document.getElementById('an-body');
    body.innerHTML = '<div id="an-loading" style="color:#555;text-align:center;padding:40px 0">Carregando dados...</div>';
    try {
      const d = await fetch('/api/analytics').then(r => r.json());
      const s = d.summary || {};
      const bench = d.benchmark_history || [];
      const byDay = d.messages_by_day || [];
      const byHour = d.messages_by_hour || [];
      const topTopics = d.top_topics || [];
      const topWords = d.top_words || [];

      const maxDay = Math.max(1, ...byDay.map(x => x.count));
      const maxHour = Math.max(1, ...byHour.map(x => x.count));
      const maxTopic = Math.max(1, ...(topTopics[0] ? [topTopics[0].count] : [1]));
      const maxWord = Math.max(1, ...(topWords[0] ? [topWords[0].count] : [1]));
      const todayStr = new Date().toISOString().slice(0, 10);

      body.innerHTML = `
        <!-- Estou melhorando? (M9 9.3) — preenchido por _loadImproving() -->
        <div class="an-section" id="an-improving">
          <h3>📈 Estou melhorando?
            <button onclick="runCanaryFromAnalytics()" style="margin-left:auto;background:#0a1f0a;border:1px solid #1a4a1a;color:#4ade80;padding:3px 10px;border-radius:6px;cursor:pointer;font-size:11px" id="an-canary-run-btn">▶ Rodar avaliação</button>
          </h3>
          <div id="an-improving-body"><div style="color:#555;font-size:12px;padding:8px 0">Carregando avaliação…</div></div>
        </div>

        <!-- Hero stats -->
        <div class="an-section">
          <div class="an-hero">
            <div class="an-stat"><div class="num">${s.total_messages ?? 0}</div><div class="lbl">Perguntas feitas</div></div>
            <div class="an-stat"><div class="num">${s.total_topics_studied ?? 0}</div><div class="lbl">Tópicos estudados</div></div>
            <div class="an-stat"><div class="num">${s.days_active ?? 0}</div><div class="lbl">Dias ativos</div></div>
            <div class="an-stat"><div class="num">${s.est_hours ?? 0}h</div><div class="lbl">Horas estimadas</div></div>
          </div>
        </div>

        <!-- Uso nos últimos 30 dias -->
        <div class="an-section">
          <h3>📅 Atividade — últimos 30 dias</h3>
          <div class="an-timeline" id="an-timeline"></div>
          <div style="display:flex;justify-content:space-between;font-size:9px;color:#444;margin-top:4px">
            <span>${byDay[0]?.date ?? ''}</span><span>hoje</span>
          </div>
        </div>

        <!-- Distribuição por hora -->
        <div class="an-section">
          <h3>🕐 Quando você mais usa</h3>
          <div class="an-hours" id="an-hours"></div>
          <div style="display:flex;justify-content:space-between;font-size:9px;color:#444;margin-top:4px">
            <span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
          </div>
        </div>

        <!-- Duas colunas: tópicos + palavras -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
          <div class="an-section">
            <h3>📚 Tópicos mais estudados</h3>
            <div id="an-topics"></div>
          </div>
          <div class="an-section">
            <h3>💬 Palavras mais usadas</h3>
            <div id="an-words"></div>
          </div>
        </div>

        <!-- Benchmark histórico -->
        <div class="an-section" id="an-bench-section">
          <h3>🎯 Evolução do Benchmark
            <button onclick="runBenchmarkFromAnalytics()" style="margin-left:auto;background:#0a1f0a;border:1px solid #1a4a1a;color:#4ade80;padding:3px 10px;border-radius:6px;cursor:pointer;font-size:11px" id="an-bench-run-btn">▶ Rodar agora</button>
          </h3>
          <div id="an-bench-list"></div>
        </div>
      `;

      // Preenche timeline de dias
      const tl = document.getElementById('an-timeline');
      byDay.forEach(d => {
        const col = document.createElement('div');
        col.className = 'an-day-col';
        const pct = d.count === 0 ? 0 : Math.max(4, Math.round((d.count / maxDay) * 100));
        const bar = document.createElement('div');
        bar.className = 'an-day-bar' + (d.date === todayStr ? ' today' : '');
        bar.style.height = pct + '%';
        bar.title = `${d.date}: ${d.count} msg`;
        col.appendChild(bar);
        tl.appendChild(col);
      });

      // Preenche horas
      const hGrid = document.getElementById('an-hours');
      byHour.forEach(h => {
        const cell = document.createElement('div');
        cell.className = 'an-hour-cell';
        const alpha = h.count === 0 ? 0.05 : 0.15 + (h.count / maxHour) * 0.85;
        cell.style.background = `rgba(74,222,128,${alpha.toFixed(2)})`;
        cell.title = `${String(h.hour).padStart(2,'0')}h: ${h.count} msg`;
        hGrid.appendChild(cell);
      });

      // Tópicos
      const topEl = document.getElementById('an-topics');
      (topTopics.slice(0, 12)).forEach(t => {
        topEl.innerHTML += `<div class="an-bar-row">
          <div class="an-bar-label" title="${escHtml(t.topic)}">${escHtml(t.topic.slice(0,28))}</div>
          <div class="an-bar-track"><div class="an-bar-fill green" style="width:${Math.round(t.count/maxTopic*100)}%"></div></div>
          <div class="an-bar-num">${t.count}</div>
        </div>`;
      });
      if (!topTopics.length) topEl.innerHTML = '<div style="color:#444;font-size:12px;padding:8px 0">Nenhum tópico estudado ainda</div>';

      // Palavras
      const wordsEl = document.getElementById('an-words');
      (topWords.slice(0, 12)).forEach(w => {
        wordsEl.innerHTML += `<div class="an-bar-row">
          <div class="an-bar-label">${escHtml(w.word)}</div>
          <div class="an-bar-track"><div class="an-bar-fill blue" style="width:${Math.round(w.count/maxWord*100)}%"></div></div>
          <div class="an-bar-num">${w.count}</div>
        </div>`;
      });
      if (!topWords.length) wordsEl.innerHTML = '<div style="color:#444;font-size:12px;padding:8px 0">Nenhuma mensagem ainda</div>';

      // Benchmark
      const benchEl = document.getElementById('an-bench-list');
      if (!bench.length) {
        benchEl.innerHTML = '<div style="color:#444;font-size:12px;padding:8px 0">Nenhum run ainda — clique em ▶ Rodar agora</div>';
      } else {
        bench.forEach((r, i) => {
          const dt = new Date(r.ran_at).toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
          const prev = bench[i - 1];
          const delta = prev != null ? (r.avg_score - prev.avg_score) : null;
          const arrow = delta == null ? '' : delta > 0.005 ? ' ▲' : delta < -0.005 ? ' ▼' : ' ≈';
          const arrowColor = delta == null ? '' : delta > 0.005 ? '#4ade80' : delta < -0.005 ? '#f87171' : '#888';
          benchEl.innerHTML += `<div class="an-bench-row">
            <div class="an-bench-ts">${dt}</div>
            <div class="an-bench-score" style="color:${_scoreColor(r.avg_score)}">${(r.avg_score*100).toFixed(0)}%<span style="color:${arrowColor};font-size:10px">${arrow}</span></div>
            <div class="an-bench-bar"><div class="an-bench-fill" style="width:${Math.round((r.avg_score??0)*100)}%;background:${_scoreColor(r.avg_score)}"></div></div>
            <div class="an-bench-lat">${r.avg_latency_ms ?? '—'}ms</div>
          </div>`;
        });
      }

      _loadImproving();   // M9 9.3 — assíncrono, isolado (não bloqueia o painel)

    } catch(e) {
      document.getElementById('an-body').innerHTML =
        `<div style="color:#f87171;padding:20px">Erro ao carregar analytics: ${escHtml(e.message)}</div>`;
    }
  }

  // M9 9.3 — "Estou melhorando?": veredito + eixos com setas + sparkline das notas.
  async function _loadImproving() {
    const el = document.getElementById('an-improving-body');
    if (!el) return;
    try {
      const d = await fetch('/api/improving').then(r => r.json());
      const rep = d.report || {}; const axes = rep.axes || [];
      const latest = d.latest; const series = d.series || [];
      const VERD = {
        melhorando: ['🟢', 'Melhorando', '#4ade80'],
        piorando:   ['🔴', 'Piorando', '#f87171'],
        estavel:    ['🟡', 'Estável', '#eab308'],
        sem_dados:  ['⚪', 'Sem dados ainda', '#888'],
      };
      const [emoji, txt, col] = VERD[rep.verdict] || VERD.sem_dados;

      const axHtml = axes.map(a => {
        if (!a.known) return `<div class="an-axis"><span class="an-axis-lbl">${escHtml(a.label)}</span><span style="color:#555">— sem dados</span></div>`;
        const arrow = a.direction === 'up' ? '▲' : a.direction === 'down' ? '▼' : '≈';
        const c = a.direction === 'up' ? '#4ade80' : a.direction === 'down' ? '#f87171' : '#888';
        return `<div class="an-axis"><span class="an-axis-lbl">${escHtml(a.label)}</span>
          <span style="color:${c};font-weight:600">${arrow} ${a.delta > 0 ? '+' : ''}${a.delta}</span></div>`;
      }).join('');

      // Sparkline SVG das notas do canário (antigo → recente)
      let spark = '';
      if (series.length >= 2) {
        const W = 220, H = 34, n = series.length;
        const pts = series.map((p, i) => {
          const x = (i / (n - 1)) * W;
          const y = H - (Math.max(0, Math.min(1, p.score ?? 0)) * H);
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');
        spark = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="margin-top:6px">
          <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/></svg>`;
      }

      const latestHtml = latest ? `<div style="font-size:11px;color:#888;margin-top:6px">
        Último canário: <b style="color:${_scoreColor(latest.score)}">${((latest.score ?? 0)*100).toFixed(0)}%</b>
        · alucinação: <b style="color:${latest.hallucination_rate > 0 ? '#f87171' : '#4ade80'}">${((latest.hallucination_rate ?? 0)*100).toFixed(0)}%</b></div>` : '';

      el.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span style="font-size:20px">${emoji}</span>
          <span style="font-size:15px;font-weight:700;color:${col}">${txt}</span>
        </div>
        <div class="an-axes">${axHtml}</div>
        ${spark}
        ${latestHtml}`;
    } catch(e) {
      el.innerHTML = `<div style="color:#f87171;font-size:12px">Erro ao avaliar: ${escHtml(e.message)}</div>`;
    }
  }

  async function runCanaryFromAnalytics() {
    const btn = document.getElementById('an-canary-run-btn');
    if (!btn) return;
    btn.textContent = '⏳ Avaliando… (~6 inferências)';
    btn.disabled = true;
    try {
      await fetch('/api/evals/run', { method: 'POST' });
      await _loadImproving();
    } catch {}
    const b2 = document.getElementById('an-canary-run-btn');
    if (b2) { b2.textContent = '▶ Rodar avaliação'; b2.disabled = false; }
  }

  async function runBenchmarkFromAnalytics() {
    const btn = document.getElementById('an-bench-run-btn');
    if (!btn) return;
    btn.textContent = '⏳ Rodando…';
    btn.disabled = true;
    try {
      await fetch('/api/benchmark/run', { method: 'POST' });
      await loadAnalytics();
    } catch(e) {
      btn.textContent = '✗ Erro';
      setTimeout(() => { btn.textContent = '▶ Rodar agora'; btn.disabled = false; }, 2000);
    }
  }

  async function loadHealth() {
    const body = document.getElementById('health-body');
    body.textContent = 'Carregando…';
    try {
      const [h, perf] = await Promise.all([
        fetch('/api/health').then(r=>r.json()),
        fetch('/api/perf').then(r=>r.json()).catch(()=>null),
      ]);
      const dot = (ok)=>`<span style="color:${ok?'#4ade80':'#f87171'}">●</span>`;
      const card = (title, rows)=>`
        <div style="background:#15151b;border:1px solid #23232c;border-radius:9px;padding:11px 13px;margin-bottom:10px">
          <div style="color:#ddd;font-weight:600;margin-bottom:6px">${title}</div>${rows}</div>`;
      const line = (k,v)=>`<div style="display:flex;justify-content:space-between"><span style="color:#888">${k}</span><span>${v}</span></div>`;

      const o = h.ollama || {};
      const backendLabel = o.backend === 'llamacpp'
        ? '<span style="color:#a78bfa">motor próprio (llama.cpp)</span>'
        : '<span style="color:#5eead4">Ollama</span>';
      const hw = o.hardware || {};
      const profLabel = hw.profile === 'max'
        ? '<span style="color:#fbbf24">máx (dedicada)</span>'
        : '<span style="color:#888">balanceado</span>';
      const ollamaCard = card(`${dot(o.installed&&o.installed.length)} 🧩 Motor de inferência`,
        line('Backend', backendLabel) +
        line('Chat', escHtml(o.chat_model||'—')) +
        line('Pesado (14b)', escHtml(o.heavy_model||'—')) +
        line('Visão', o.has_vision ? escHtml(o.vision_model) : '<span style="color:#888">não instalado</span>') +
        line('Modelos disponíveis', (o.installed||[]).length) +
        (hw.profile ? (
          line('Perfil de performance', profLabel) +
          line('Threads', escHtml(String(hw.num_thread)) + ` / ${hw.cpu_count} CPUs`) +
          line('Contexto', escHtml(String(hw.num_ctx))) +
          line('Modelo quente (pesado)', escHtml(String(hw.keep_alive_heavy)))
        ) : ''));

      const db_ = h.database || {};
      const q = db_.quality || {};
      // Qualidade da base: % de sínteses estruturadas (##) vs cruas (lixo de
      // timeouts antigos — o botão 🩹 Reparar na Mente conserta).
      let qualLine = '';
      if (q.total) {
        const pct = q.pct_structured ?? 0;
        const pctColor = pct >= 90 ? '#4ade80' : pct >= 60 ? '#facc15' : '#f87171';
        qualLine = line('Qualidade das sínteses',
          `<span style="color:${pctColor}" title="${q.structured} estruturadas · ${q.raw} cruas · ${q.short} curtas">${pct}% estruturadas</span>`
          + ((q.raw ?? 0) > 0 ? ` <span style="color:#f87171;cursor:pointer" title="Re-sintetizar as cruas — Mente → 🩹 Reparar" onclick="openMind();setTimeout(repairSummaries, 600)">· 🩹 ${q.raw} cruas</span>` : ''));
      }
      const dbCard = card(`${dot(!db_.error)} 💾 Banco local`,
        line('Conhecimentos', db_.learned_total ?? '—') +
        line('Aprendidos hoje', db_.learned_today ?? '—') +
        line('Conversas salvas', db_.sessions ?? '—') +
        line('Duplicatas', (db_.duplicates ?? 0) > 0 ? `<span style="color:#facc15">${db_.duplicates}</span>` : '0') +
        qualLine);

      const sb = h.supabase || {};
      const brk = sb.breaker || {};
      const brkLabel = { closed: '<span style="color:#4ade80">fechado (ok)</span>',
                         half_open: '<span style="color:#facc15">testando</span>',
                         open: '<span style="color:#f87171">ABERTO (fora do ar)</span>' };
      const sbHealthy = sb.enabled && !sb.error && !sb.save_errors && brk.state !== 'open';
      const sbCard = card(`${dot(sbHealthy)} ☁️ Supabase (conhecimento)`,
        !sb.enabled ? '<span style="color:#888">não configurado</span>' :
        (line('Total de artigos', sb.total ?? '—') +
         line('Subidos nesta sessão', sb.saved_session ?? 0) +
         line('Falhas de upload', (sb.save_errors||0) > 0 ? `<span style="color:#f87171">${sb.save_errors}</span>` : '0') +
         (brk.state ? line('Conexão (circuit breaker)', brkLabel[brk.state] || escHtml(brk.state)) : '') +
         (sb.last_error ? line('Último erro', `<span style="color:#f87171" title="${escHtml(sb.last_error)}">${escHtml(sb.last_error.slice(0,40))}…</span>`) : '')));

      const l = h.learner || {};
      const activeNames = (l.active_agents||[]).map(a=>a.name).join(', ') || '—';
      const learnerCard = card(`${dot(l.running)} 🎓 Aprendizado contínuo`,
        line('Status', l.running ? '<span style="color:#4ade80">ativo</span>' : '<span style="color:#888">parado</span>') +
        (l.running ? (
          line('Fila de estudo', l.queue_depth ?? 0) +
          line('Estudados (sessão)', l.total_session ?? 0) +
          line('Ritmo', (l.throughput_hour ?? 0) + '/h') +
          line('Lacunas detectadas', l.gap_count ?? 0) +
          line('Agentes ativos', escHtml(activeNames))
        ) : ''));

      const rc = h.recall || {};
      const pct = (v)=> v==null ? '—' : Math.round(v*100)+'%';
      const recallOk = (rc.avg_score==null) || rc.avg_score >= 0.45;
      const recallCard = card(`${dot(recallOk)} 🎯 Qualidade do recall`,
        rc.error ? `<span style="color:#f87171">${escHtml(rc.error)}</span>` :
        (line('Docs no índice', rc.index_docs ?? '—') +
         line('Amostras testadas', rc.samples ?? 0) +
         line('Score médio', `<span style="color:${recallOk?'#4ade80':'#facc15'}">${pct(rc.avg_score)}</span>`) +
         line('Relevância vetorial', pct(rc.avg_relevance)) +
         line('Casamento lexical', pct(rc.avg_lexical))));

      let perfCard = '';
      if (perf && perf.routes && perf.routes.length) {
        // Verde se o endpoint mais lento (média) estiver < 800ms.
        const top = perf.routes.slice(0, 6);
        const perfOk = top.every(r => r.avg_ms < 800);
        const colorMs = (ms)=> ms < 300 ? '#4ade80' : ms < 800 ? '#facc15' : '#f87171';
        const rows = top.map(r =>
          `<div style="display:flex;justify-content:space-between;gap:8px">
             <span style="color:#888;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(r.route)}">${escHtml(r.route.replace('/api/',''))}</span>
             <span style="white-space:nowrap"><span style="color:${colorMs(r.avg_ms)}">${r.avg_ms}ms</span> <span style="color:#666">p95 ${r.p95_ms} · ${r.count}×${r.errors?` · <span style="color:#f87171">${r.errors}err</span>`:''}</span></span>
           </div>`).join('');
        perfCard = card(`${dot(perfOk)} ⚡ Latência por endpoint <span style="font-weight:400;color:#666;font-size:10px">(${perf.total_requests} reqs)</span>`,
          rows + `<div style="margin-top:7px;text-align:right"><button onclick="fetch('/api/perf/reset',{method:'POST'}).then(()=>loadHealth())" style="background:none;border:1px solid #2a2a33;color:#888;border-radius:6px;padding:3px 9px;cursor:pointer;font-size:10px">Zerar métricas</button></div>`);
      }

      const b = h.build || {};
      const buildFooter = b.version
        ? `<div style="text-align:center;color:#666;font-size:10.5px;margin-top:6px">
             A.P.O.L.O. v${escHtml(b.version)} · <span title="commit em execução">${escHtml(b.git_sha||'—')}</span> · no ar há ${escHtml(b.uptime_human||'—')}</div>`
        : '';
      body.innerHTML = ollamaCard + learnerCard + recallCard + perfCard + dbCard + sbCard + buildFooter;
    } catch (e) {
      body.innerHTML = '<span style="color:#f87171">Falha ao carregar saúde do sistema</span>';
    }
  }

  async function resumeSession(sid) {
    if (sid === sessionId) { closeCoder(); return; }
    closeCoder();
    sessionId = sid;
    localStorage.setItem('apoloSessionId', sessionId);
    document.getElementById('messages').innerHTML = '';
    try {
      const data = await fetch(`/api/session/${sid}`).then(r=>r.json());
      for (const msg of data.messages) {
        if (msg.role === 'user') { addUserMessage(msg.content); }
        else {
          const wrap = document.createElement('div');
          wrap.className = 'message-wrap';
          wrap.innerHTML = `<div class="msg-ai"><div class="avatar">☀️</div><div class="content"><div class="md-body">${renderMd(msg.content)}</div></div></div>`;
          document.getElementById('messages').appendChild(wrap);
          wrap.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
        }
      }
      scrollBottom();
    } catch {}
    loadSessions();
  }

  async function restoreSession() {
    try {
      const data = await fetch(`/api/session/${sessionId}`).then(r=>r.json());
      if (!data.messages?.length) return;
      document.getElementById('empty-state')?.remove();
      for (const msg of data.messages) {
        if (msg.role === 'user') { addUserMessage(msg.content); }
        else {
          const wrap = document.createElement('div');
          wrap.className = 'message-wrap';
          wrap.innerHTML = `<div class="msg-ai"><div class="avatar">☀️</div><div class="content"><div class="md-body">${renderMd(msg.content)}</div></div></div>`;
          document.getElementById('messages').appendChild(wrap);
          wrap.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
        }
      }
      scrollBottom();
    } catch {}
  }

  // ── Chat ─────────────────────────────────────────────────────
  function addUserMessage(text, imageDataUrl) {
    document.getElementById('empty-state')?.remove();
    const wrap = document.createElement('div');
    wrap.className = 'message-wrap';
    const img = imageDataUrl ? `<img class="msg-img" src="${imageDataUrl}" alt="imagem enviada" />` : '';
    wrap.innerHTML = `<div class="msg-user"><div class="bubble">${img}${escHtml(text)}</div></div>`;
    document.getElementById('messages').appendChild(wrap);
    scrollBottom();
  }

  // ── Visão: anexar imagem ─────────────────────────────────────
  function attachImage(file) {
    if (!file) return;
    if (!visionAvailable) {
      showIngestToast('🖼️ Para analisar imagens, baixe um modelo de visão: <code>ollama pull llava</code>', 6000);
      return;
    }
    if (file.size > 6 * 1024 * 1024) { showIngestToast('⚠ Imagem muito grande (máx. 6MB).'); return; }
    const fr = new FileReader();
    fr.onload = () => { pendingImage = fr.result; showImagePreview(); };
    fr.readAsDataURL(file);
  }

  function showImagePreview() {
    const p = document.getElementById('img-preview');
    p.innerHTML = `<img src="${pendingImage}" alt="prévia" /><span class="img-label">imagem anexada</span><button class="img-x" onclick="clearImage()">✕ remover</button>`;
    p.classList.add('show');
    document.getElementById('image-btn').classList.add('has-img');
    document.getElementById('input').focus();
  }

  function clearImage() {
    pendingImage = '';
    const p = document.getElementById('img-preview');
    p.classList.remove('show'); p.innerHTML = '';
    document.getElementById('image-btn').classList.remove('has-img');
  }

  function createAiMessage() {
    const wrap = document.createElement('div');
    wrap.className = 'message-wrap';
    // #2: indicador de digitação (dots) antes do primeiro token
    const dots = createTypingIndicator();
    wrap.innerHTML = `<div class="msg-ai"><div class="avatar">☀️</div><div class="content">
      <div class="status-line" id="sl"><div class="spinner"></div><span id="st">Pensando...</span></div>
      <div class="stream-text"></div></div></div>`;
    wrap.querySelector('.content').insertBefore(dots, wrap.querySelector('#sl'));
    document.getElementById('messages').appendChild(wrap);
    scrollBottom();
    return wrap;
  }

  function finalizeAiMessage(wrap, data) {
    const content = wrap.querySelector('.content');
    wrap.querySelector('#sl')?.remove();
    wrap.querySelector('.stream-text')?.remove();

    if (!data.has_code) {
      const div = document.createElement('div');
      div.className = 'md-body';
      div.innerHTML = renderMd(data.code || '');
      content.appendChild(div);
      div.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
      _enrichAiMessage(content, data.code || '');  // #2 typing cleanup, #3 reactions, #4 copy buttons
      if (data.memory_sources?.length) content.appendChild(buildKbSources(data.memory_sources));
      else if (data.gap) content.appendChild(buildGapNote());
      if (data.web_sources?.length) content.appendChild(buildSources(data.web_sources));
      content.appendChild(buildRegenButton());
      { const sb = buildSpeakButton(data.code || ''); if (sb) content.appendChild(sb); }
      if (data.smart) content.appendChild(buildSmartBadge(data.auto_smart));
      scrollBottom(); loadSessions();
      _saveTabs(); // #10 snapshot da aba após cada resposta
      return;
    }

    const cid = 'c' + Date.now();
    const card = document.createElement('div');
    const statusBadge = data.success===true ? '<span class="status-badge status-ok">✓ Executado</span>'
                      : data.success===false ? '<span class="status-badge status-err">✗ Erro</span>' : '';
    const outputHtml = data.success && data.output ? `<div class="exec-output">${escHtml(data.output)}</div>`
                     : !data.success && data.error  ? `<div class="exec-output has-error">${escHtml(data.error)}</div>` : '';
    card.innerHTML = `
      ${data.explanation ? `<div class="md-body" style="margin-bottom:12px">${renderMd(data.explanation)}</div>` : ''}
      <div class="code-card">
        <div class="code-header">
          <span class="code-lang">python</span>
          <div class="code-actions">${statusBadge}<button class="copy-btn" onclick="copyCode('${cid}')">Copiar</button></div>
        </div>
        <pre><code id="${cid}" class="language-python">${escHtml(data.code)}</code></pre>
        ${outputHtml}
      </div>`;
    content.appendChild(card);
    card.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
    _enrichAiMessage(content, data.explanation || data.code || ''); // #3 reações, #4 copy
    if (data.memory_sources?.length) content.appendChild(buildKbSources(data.memory_sources));
    else if (data.gap) content.appendChild(buildGapNote());
    if (data.web_sources?.length) content.appendChild(buildSources(data.web_sources));
    content.appendChild(buildRegenButton());
    { const sb = buildSpeakButton(data.explanation || 'Código gerado.'); if (sb) content.appendChild(sb); }
    if (data.smart) content.appendChild(buildSmartBadge(data.auto_smart));
    scrollBottom(); loadSessions();
  }

  function buildGapNote() {
    const div = document.createElement('div');
    div.className = 'gap-note';
    div.innerHTML = '🎯 Eu ainda não tinha estudado isso — adicionei à minha fila de estudo prioritária.';
    return div;
  }

  function buildSmartBadge(auto) {
    const s = document.createElement('span');
    s.className = 'smart-tag';
    s.textContent = auto ? '🧠 14b (auto — pergunta complexa)' : '🧠 raciocínio profundo (14b)';
    return s;
  }

  function buildRegenButton() {
    const b = document.createElement('button');
    b.className = 'regen-btn';
    b.innerHTML = '↻ Regenerar';
    b.title = 'Refazer a última resposta';
    b.onclick = regenerate;
    return b;
  }

  // ── Voz: ler resposta em voz alta (TTS local do navegador) ───
  let ptVoice = null, speakingBtn = null;
  function pickVoice() {
    if (!('speechSynthesis' in window)) return;
    const vs = speechSynthesis.getVoices();
    ptVoice = vs.find(v => /pt[-_]br/i.test(v.lang)) || vs.find(v => /^pt/i.test(v.lang)) || null;
  }
  if ('speechSynthesis' in window) { speechSynthesis.onvoiceschanged = pickVoice; pickVoice(); }

  function stripForSpeech(md) {
    return (md || '')
      .replace(/```[\s\S]*?```/g, '. (bloco de código) .')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/[#*_>]/g, '')
      .replace(/\n{2,}/g, '. ')
      .trim();
  }

  function speak(text, btn) {
    if (!('speechSynthesis' in window)) return;
    const wasThis = speakingBtn === btn;
    if (speechSynthesis.speaking) { speechSynthesis.cancel(); if (speakingBtn) speakingBtn.textContent = '🔊'; speakingBtn = null; if (wasThis) return; }
    const u = new SpeechSynthesisUtterance(stripForSpeech(text).slice(0, 4000));
    u.lang = 'pt-BR'; if (ptVoice) u.voice = ptVoice; u.rate = 1.05;
    u.onend = () => { if (btn) btn.textContent = '🔊'; speakingBtn = null; };
    if (btn) { btn.textContent = '⏹'; speakingBtn = btn; }
    speechSynthesis.speak(u);
  }

  // ── Verificação anti-alucinação (M7 7.2) ──────────────────────
  // Depois de uma resposta FACTUAL, pergunta ao /api/verify se ela está ancorada
  // na base. Só mostra um aviso quando NÃO está (baixa correspondência ou sem
  // fonte) — sem poluir quando a resposta tem lastro. Nunca bloqueia o chat.
  async function verifyAndBadge(aiWrap, question, answer) {
    if (!aiWrap || !answer || answer.length < 40) return;
    try {
      const v = await fetch('/api/verify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, answer }),
      }).then(r => r.json());
      if (!v.checked || !v.note) return;             // não-factual ou bem ancorado
      const content = aiWrap.querySelector('.content');
      if (!content || content.querySelector('.verify-chip')) return;
      const chip = document.createElement('div');
      chip.className = 'verify-chip';
      chip.textContent = v.note + (v.sources_count ? ` (base: ${v.sources_count} fonte(s))` : '');
      content.appendChild(chip);
    } catch { /* verificação é best-effort */ }
  }

  function buildSpeakButton(text) {
    if (!('speechSynthesis' in window)) return null;
    const b = document.createElement('button');
    b.className = 'regen-btn speak-btn';
    b.textContent = '🔊'; b.title = 'Ouvir a resposta';
    b.onclick = () => speak(text, b);
    return b;
  }

  // ── Briefing do dia (M4 4.1): o A.P.O.L.O. te resume o dia e FALA ──
  async function playBriefing() {
    const btn = document.getElementById('briefing-btn');
    if (btn) btn.textContent = '⏳';
    try {
      const b = await fetch('/api/briefing').then(r => r.json());
      showIngestToast('📻 ' + escHtml(b.text || 'Sem novidades.'), 14000);
      if (b.text) speak(b.text);
    } catch {
      showIngestToast('Não consegui montar o briefing agora.');
    } finally {
      if (btn) btn.textContent = '📻';
    }
  }

  // ── Voz: ditar por microfone ────────────────────────────────
  // Tenta Whisper local (/api/stt) primeiro; se não disponível, usa Web Speech API.
  let recog = null, recognizing = false;
  let _whisperAvailable = null; // null=não testado, true/false

  async function _checkWhisper() {
    if (_whisperAvailable !== null) return _whisperAvailable;
    try {
      const h = await fetch('/api/health').then(r => r.json());
      _whisperAvailable = !!h.stt;
    } catch { _whisperAvailable = false; }
    return _whisperAvailable;
  }

  async function _whisperRecord() {
    const mic = document.getElementById('mic-btn');
    const input = document.getElementById('input');
    let stream, recorder, chunks = [];
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch(e) { showIngestToast('⚠ Acesso ao microfone negado.'); return; }
    recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    recorder.start();
    recognizing = true; mic.classList.add('rec');
    mic.title = 'Clique para parar a gravação';
    await new Promise(resolve => {
      mic.onclick = () => resolve();
    });
    recorder.stop();
    stream.getTracks().forEach(t => t.stop());
    recognizing = false; mic.classList.remove('rec');
    mic.onclick = () => toggleMic();
    mic.title = 'Falar (ditar por voz)';
    showIngestToast('🧠 Transcrevendo com Whisper local...', 0);
    await new Promise(r => recorder.onstop = r);
    const blob = new Blob(chunks, { type: 'audio/webm' });
    try {
      const res = await fetch('/api/stt', { method: 'POST', body: blob }).then(r => r.json());
      if (res.ok && res.text) {
        input.value = (input.value + ' ' + res.text).trim();
        autoResize(input); input.focus();
        showIngestToast('✅ Transcrição pronta.', 2500);
      } else {
        showIngestToast('⚠ Não consegui transcrever. ' + (res.error || ''));
      }
    } catch(e) { showIngestToast('⚠ Falha na transcrição: ' + e.message); }
  }

  function _webSpeechMic() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { showIngestToast('⚠ Sem Whisper local e seu navegador não suporta Web Speech API (use Chrome/Edge).'); return; }
    if (recognizing) { recog && recog.stop(); return; }
    recog = new SR(); recog.lang = 'pt-BR'; recog.interimResults = true; recog.continuous = false;
    const input = document.getElementById('input'), mic = document.getElementById('mic-btn');
    let finalText = '';
    recog.onstart = () => { recognizing = true; mic.classList.add('rec'); };
    recog.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t; else interim += t;
      }
      input.value = (finalText + interim).trim(); autoResize(input);
    };
    recog.onerror = () => {};
    recog.onend = () => { recognizing = false; mic.classList.remove('rec'); input.focus(); };
    recog.start();
  }

  async function toggleMic() {
    if (recognizing) { recog && recog.stop(); return; }
    const hasWhisper = await _checkWhisper();
    if (hasWhisper) {
      _whisperRecord();
    } else {
      _webSpeechMic();
    }
  }

  // ── Palavra de ativação (M5 5.1): "Apolo, ..." sem tocar no PC ──
  // Escuta contínua (Web Speech) → /api/wake/detect (detecção LOCAL, determinística)
  // → despacha o comando por /api/agency/ask e FALA a resposta. Barge-in: uma nova
  // ativação corta a fala anterior (speak() cancela se já estiver falando).
  let _wakeRecog = null, _wakeOn = false, _wakeBusy = false;

  function toggleWakeWord() {
    const btn = document.getElementById('wake-btn');
    if (_wakeOn) { _wakeOn = false; try { _wakeRecog && _wakeRecog.stop(); } catch {}
      if (btn) btn.classList.remove('rec'); showIngestToast('👂 Palavra de ativação desligada.'); return; }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { showIngestToast('⚠ Seu navegador não suporta escuta contínua (use Chrome/Edge).'); return; }
    _wakeOn = true;
    if (btn) btn.classList.add('rec');
    showIngestToast('👂 Ouvindo… diga "Apolo, que horas são?"');
    _startWakeRecog(SR);
  }

  function _startWakeRecog(SR) {
    _wakeRecog = new SR();
    _wakeRecog.lang = 'pt-BR'; _wakeRecog.continuous = true; _wakeRecog.interimResults = false;
    // Barge-in (5.2): no instante em que você começa a falar, corta a fala do
    // assistente — não precisa esperar ele terminar pra dar o próximo comando.
    _wakeRecog.onspeechstart = () => { if (speechSynthesis.speaking) speechSynthesis.cancel(); };
    _wakeRecog.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) _wakeHeard(e.results[i][0].transcript);
      }
    };
    // Recognition contínuo cai sozinho de tempos em tempos → reinicia enquanto ligado.
    _wakeRecog.onend = () => { if (_wakeOn) { try { _wakeRecog.start(); } catch {} } };
    _wakeRecog.onerror = (ev) => { if (ev.error === 'not-allowed') { _wakeOn = false;
      document.getElementById('wake-btn')?.classList.remove('rec');
      showIngestToast('⚠ Permita o microfone para a palavra de ativação.'); } };
    try { _wakeRecog.start(); } catch {}
  }

  async function _wakeHeard(transcript) {
    if (_wakeBusy) return;
    try {
      const d = await fetch('/api/wake/detect', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({text: transcript})}).then(r=>r.json());
      if (!d.woke) return;
      _wakeBusy = true;
      if (!d.command) { showIngestToast('👂 Sim? Pode falar.'); _wakeBusy = false; return; }
      // Despacha o comando pela ponte de agência (mesma porteira de permissão).
      const ans = await fetch('/api/agency/ask', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({text: d.command})}).then(r=>r.json());
      const msg = ans.answer || 'Não entendi o pedido.';
      showIngestToast('🗣️ ' + escHtml(msg), 12000);
      speak(msg);                          // barge-in embutido: corta fala anterior
    } catch { /* ignora — segue ouvindo */ }
    finally { setTimeout(() => { _wakeBusy = false; }, 500); }
  }

  function buildSources(sources) {
    const div = document.createElement('div');
    div.className = 'web-sources';
    div.innerHTML = `<div class="web-sources-label">🌐 Fontes da web</div>` +
      sources.map(s=>`<a class="web-source-item" href="${escHtml(s.url)}" target="_blank" rel="noopener">${escHtml(s.title||s.url)}</a>`).join('');
    return div;
  }

  // M7 7.1 / M8 8.3 — Roteador de tarefa: comando de agência curto (relógio/
  // agenda/e-mail/arquivos) ou pergunta de CONEXÃO ("como X se conecta com Y?")
  // são respondidos SEM gastar o LLM. Retorna true se tratou.
  async function _tryAgencyCommand(text) {
    let r;
    try {
      r = await fetch('/api/route', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({text})}).then(x=>x.json());
    } catch { return false; }
    if (!r || (r.route !== 'tool' && r.route !== 'connect')) return false;
    addUserMessage(text);
    const wrap = createAiMessage();
    try {
      let answer;
      if (r.route === 'connect') {
        const c = await fetch('/api/graph/connect?a=' + encodeURIComponent(r.a) +
          '&b=' + encodeURIComponent(r.b)).then(x=>x.json());
        answer = c.answer || 'Não achei uma conexão.';
      } else {
        const ans = await fetch('/api/agency/ask', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({text})}).then(x=>x.json());
        answer = ans.answer || 'Não entendi o pedido.';
      }
      wrap.querySelector('#sl')?.remove();
      wrap.querySelector('.stream-text')?.remove();
      wrap.querySelector('.content').innerHTML = renderMd(answer);
    } catch {
      wrap.querySelector('.content').innerHTML =
        '<div style="color:#f87171;font-size:13px">Falha ao responder.</div>';
    }
    lastUserText = text; lastImage = '';
    scrollBottom();
    return true;
  }

  async function sendMessage() {
    if (busy) return;
    const input = document.getElementById('input');
    let text = input.value.trim();
    if (!text && !pendingImage) return;

    // Imagem anexada → conversa de VISÃO (ignora research/web/comandos)
    if (pendingImage) {
      if (!text) text = 'O que você vê nesta imagem? Descreva e analise.';
      const img = pendingImage;
      input.value = ''; input.style.height = 'auto';
      addUserMessage(text, img);
      clearImage();
      lastUserText = text; lastNeedsWeb = false; lastSmart = false; lastImage = img;
      await streamChatResponse(text, false, false, img);
      return;
    }

    if (useAgent) { return runAgent(text); }
    if (useResearch) { return runResearch(text); }
    if (useMulti) { return runMultiAgent(text); }

    // Memorizar um fato sobre você: "/remember <fato>"
    const rememberMatch = text.match(/^\/remember\s+(.+)/i);
    if (rememberMatch) { input.value = ''; input.style.height = 'auto'; return rememberFact(rememberMatch[1].trim()); }

    // Ensinar um link: "/learn <url>" ou uma URL sozinha → ingere em vez de conversar
    const urlMatch = text.match(/^\/learn\s+(\S+)/i) || (/^https?:\/\/\S+$/i.test(text) ? [null, text] : null);
    if (urlMatch) { input.value = ''; input.style.height = 'auto'; return ingestUrl(urlMatch[1]); }

    // M7 7.1 — comando de agência (sem web/smart explícito)? Trata sem o LLM.
    if (!useWeb && !useSmart && await _tryAgencyCommand(text)) {
      input.value = ''; input.style.height = 'auto';
      return;
    }

    const needsWeb = useWeb || /^\/web\s/.test(text) ||
      /(última versão|release notes|changelog|como instalar|docs? oficial|novidade|lançament)/i.test(text);

    input.value = ''; input.style.height = 'auto';
    addUserMessage(text);
    lastUserText = text; lastNeedsWeb = needsWeb; lastSmart = useSmart; lastImage = '';
    await streamChatResponse(text, needsWeb, useSmart, '');
  }

  // Refaz a última resposta (sem repetir a bolha do usuário).
  async function regenerate() {
    if (busy || !lastUserText) return;
    const wraps = [...document.querySelectorAll('#messages .message-wrap')];
    for (let i = wraps.length - 1; i >= 0; i--) {
      if (wraps[i].querySelector('.msg-ai')) { wraps[i].remove(); break; }
    }
    await streamChatResponse(lastUserText, lastNeedsWeb, lastSmart, lastImage);
  }

  function onSendClick() { busy ? stopGeneration() : sendMessage(); }
  function stopGeneration() { if (currentAbort) currentAbort.abort(); }

  function setSending(on) {
    const b = document.getElementById('send-btn');
    b.classList.toggle('stopping', on);
    b.title = on ? 'Parar geração' : 'Enviar (Enter)';
    b.innerHTML = on
      ? '<svg width="13" height="13" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="3" fill="currentColor"/></svg>'
      : '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
  }

  function finalizePartial(aiWrap, partial) {
    const content = aiWrap.querySelector('.content');
    aiWrap.querySelector('#sl')?.remove();
    aiWrap.querySelector('.stream-text')?.remove();
    if (partial.trim()) {
      const div = document.createElement('div');
      div.className = 'md-body';
      div.innerHTML = renderMd(partial);
      content.appendChild(div);
      div.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
    }
    const note = document.createElement('div');
    note.className = 'gap-note'; note.style.color = '#9a7070'; note.style.borderColor = '#3a2020'; note.style.background = '#1a1012';
    note.textContent = '⏹ Geração interrompida.';
    content.appendChild(note);
  }

  async function streamChatResponse(text, needsWeb, smart, imageDataUrl) {
    busy = true;
    setSending(true);
    const aiWrap = createAiMessage();
    const streamEl = aiWrap.querySelector('.stream-text');
    let streaming = false, acc = '';
    currentAbort = new AbortController();
    const imgB64 = imageDataUrl ? (imageDataUrl.split(',', 2)[1] || '') : '';

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId, use_web: needsWeb, smart: !!smart, image: imgB64 }),
        signal: currentAbort.signal,
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const data = JSON.parse(part.slice(6));
          if (data.type === 'status') {
            const el = aiWrap.querySelector('#st');
            if (el) el.textContent = data.message;
          } else if (data.type === 'token') {
            if (!streaming) { aiWrap.querySelector('#sl')?.remove(); streaming = true; }
            acc += data.content; streamEl.textContent = acc;
            scrollBottom();
          } else if (data.type === 'done') {
            finalizeAiMessage(aiWrap, data);
            verifyAndBadge(aiWrap, text, acc);   // M7 7.2: sinaliza incerteza factual
          } else if (data.type === 'error') {
            aiWrap.querySelector('.content').innerHTML =
              `<div style="color:#f87171;font-size:13px;padding:6px 0">⚠ ${escHtml(data.message)}</div>`;
          }
        }
      }
    } catch(e) {
      if (e.name === 'AbortError') finalizePartial(aiWrap, acc);
      else aiWrap.querySelector('.content').innerHTML =
        `<div style="color:#f87171;font-size:13px">Falha: ${escHtml(e.message)}</div>`;
    } finally {
      busy = false; currentAbort = null;
      setSending(false);
      document.getElementById('input').focus();
    }
  }

  // ── Ingestão de arquivos (ensina um documento ao A.P.O.L.O.) ──
  function showIngestToast(html, ms = 4500) {
    const t = document.getElementById('ingest-toast');
    t.innerHTML = html; t.classList.add('show');
    clearTimeout(t._timer);
    if (ms) t._timer = setTimeout(() => t.classList.remove('show'), ms);
  }

  async function _ingestOneFile(file) {
    if (!file) return false;
    if (file.size > 8 * 1024 * 1024) { showIngestToast(`⚠ ${escHtml(file.name)} muito grande (máx. 8 MB).`); return false; }
    const isBinary = /\.(pdf|docx|doc)$/i.test(file.name);
    let payload;
    if (isBinary) {
      const dataUrl = await new Promise((res, rej) => {
        const fr = new FileReader(); fr.onload = () => res(fr.result); fr.onerror = rej;
        fr.readAsDataURL(file);
      });
      payload = { filename: file.name, content: dataUrl.split(',', 2)[1] || '', encoding: 'base64' };
    } else {
      payload = { filename: file.name, content: await file.text(), encoding: 'text' };
    }
    const res = await fetch('/api/ingest', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }).then(r => r.json());
    if (res.ok) {
      const c = document.getElementById('kb-count');
      c.textContent = (parseInt(c.textContent) || 0) + 1;
    }
    return res;
  }

  async function uploadDocs(files) {
    if (!files || !files.length) return;
    const btn = document.getElementById('attach-btn');
    btn.classList.add('busy'); btn.textContent = '⏳';
    const list = Array.from(files);
    if (list.length === 1) {
      showIngestToast(`📎 Processando <b>${escHtml(list[0].name)}</b>...`, 0);
      try {
        const res = await _ingestOneFile(list[0]);
        if (res && res.ok) showIngestToast(`✅ <b>${escHtml(res.filename)}</b> aprendido — ${res.chunks} trecho(s). Já posso responder sobre ele e citá-lo.`);
        else if (res) showIngestToast(`⚠ ${escHtml(res.error || 'Falha ao ingerir.')}`);
      } catch(e) { showIngestToast(`⚠ ${escHtml(e.message)}`); }
    } else {
      showIngestToast(`📎 Processando <b>${list.length} arquivos</b>...`, 0);
      let ok = 0, fail = 0;
      for (const f of list) {
        try {
          const res = await _ingestOneFile(f);
          if (res && res.ok) ok++; else fail++;
        } catch { fail++; }
      }
      showIngestToast(`✅ ${ok} arquivo(s) aprendido(s)${fail ? ` · ${fail} falhou` : ''}.`);
    }
    btn.classList.remove('busy'); btn.textContent = '📎';
  }

  function uploadDoc(file) { return uploadDocs(file ? [file] : []); }

  function handleDrop(e) {
    e.preventDefault();
    document.getElementById('input-wrap').classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files);
    const imgs = files.filter(f => f.type.startsWith('image/'));
    const docs = files.filter(f => !f.type.startsWith('image/'));
    if (imgs.length) attachImage(imgs[0]);
    if (docs.length) uploadDocs(docs);
  }

  async function ingestUrl(url) {
    const btn = document.getElementById('attach-btn');
    btn.classList.add('busy');
    showIngestToast(`🔗 Lendo <b>${escHtml(url)}</b>...`, 0);
    try {
      const r = await fetch('/api/ingest/url', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
      }).then(x => x.json());
      if (r.ok) {
        showIngestToast(`✅ Aprendi de <b>${escHtml(r.filename || url)}</b> — ${r.chunks} trecho(s). Já posso responder sobre essa página e citá-la.`);
        const c = document.getElementById('kb-count');
        c.textContent = (parseInt(c.textContent) || 0) + 1;
      } else {
        showIngestToast(`⚠ ${escHtml(r.error || 'Falha ao aprender o link.')}`);
      }
    } catch (e) {
      showIngestToast(`⚠ Falha: ${escHtml(e.message)}`);
    } finally {
      btn.classList.remove('busy');
    }
  }

  // ── Modo Pesquisa Profunda ───────────────────────────────────
  function createResearchMessage() {
    const wrap = document.createElement('div');
    wrap.className = 'message-wrap';
    wrap.innerHTML = `<div class="msg-ai"><div class="avatar">☀️</div><div class="content">
      <div class="research-trace" id="rt">
        <div class="research-trace-head"><span class="rt-spin"></span> Pesquisa Profunda</div>
        <div class="rt-steps" id="rt-steps"></div>
      </div>
      <div class="status-line" id="sl"><div class="spinner"></div><span id="st">Iniciando investigação...</span></div>
      <div class="stream-text"></div></div></div>`;
    document.getElementById('messages').appendChild(wrap);
    scrollBottom();
    return wrap;
  }

  function buildKbSources(sources) {
    const div = document.createElement('div');
    div.className = 'kb-sources';
    div.innerHTML = `<div class="kb-sources-label">📎 Fontes consultadas (${sources.length})</div>` +
      sources.map(s => {
        let tag, tagLabel;
        if (s.type === 'episodic') {
          tag = 'episodic'; tagLabel = '💬 conversa';
        } else if (s.type === 'knowledge') {
          tag = 'knowledge'; tagLabel = '📚 memória';
        } else {
          tag = 'web'; tagLabel = '🌐 web';
        }
        const inner = s.url && /^https?:/.test(s.url)
          ? `<a href="${escHtml(s.url)}" target="_blank" rel="noopener">${escHtml(s.title)}</a>`
          : `<span class="kb-source-txt">${escHtml(s.title)}</span>`;
        return `<div class="kb-source-item"><span class="kb-source-n">[${s.n}]</span><span class="kb-source-tag ${tag}">${tagLabel}</span>${inner}</div>`;
      }).join('');
    return div;
  }

  async function runResearch(text) {
    busy = true;
    document.getElementById('send-btn').disabled = true;
    const input = document.getElementById('input');
    input.value = ''; input.style.height = 'auto';

    addUserMessage(text);
    const wrap = createResearchMessage();
    const steps = wrap.querySelector('#rt-steps');
    const streamEl = wrap.querySelector('.stream-text');
    let streaming = false;

    try {
      const resp = await fetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const ev = JSON.parse(part.slice(6));

          if (ev.type === 'step') {
            const sub = /^\d+\./.test(ev.message) || ev.icon === '▸';
            const el = document.createElement('div');
            el.className = 'rt-step' + (sub ? ' rt-sub' : '');
            el.innerHTML = `<span class="rt-ico">${escHtml(ev.icon||'•')}</span><span>${escHtml(ev.message)}</span>`;
            steps.appendChild(el);
            scrollBottom();
          } else if (ev.type === 'status') {
            const st = wrap.querySelector('#st');
            if (st) st.textContent = ev.message;
          } else if (ev.type === 'token') {
            if (!streaming) { wrap.querySelector('#sl')?.remove(); streaming = true; }
            streamEl.textContent += ev.content;
            scrollBottom();
          } else if (ev.type === 'done') {
            wrap.querySelector('#sl')?.remove();
            wrap.querySelector('.stream-text')?.remove();
            wrap.querySelector('#rt')?.classList.add('done');
            const content = wrap.querySelector('.content');
            const md = document.createElement('div');
            md.className = 'md-body';
            md.innerHTML = renderMd(ev.answer || '');
            content.appendChild(md);
            md.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
            if (ev.sources?.length) content.appendChild(buildKbSources(ev.sources));
            scrollBottom(); loadSessions();
          } else if (ev.type === 'error') {
            wrap.querySelector('.content').innerHTML =
              `<div style="color:#f87171;font-size:13px;padding:6px 0">⚠ ${escHtml(ev.message)}</div>`;
          }
        }
      }
    } catch(e) {
      wrap.querySelector('.content').innerHTML =
        `<div style="color:#f87171;font-size:13px">Falha: ${escHtml(e.message)}</div>`;
    }

    busy = false;
    document.getElementById('send-btn').disabled = false;
    input.focus();
  }

  // ── Modo Agente (ReAct-lite: escreve código → executa → responde) ──
  function createAgentMessage() {
    const wrap = document.createElement('div');
    wrap.className = 'message-wrap';
    wrap.innerHTML = `<div class="msg-ai"><div class="avatar">☀️</div><div class="content">
      <div class="research-trace" id="rt">
        <div class="research-trace-head"><span class="rt-spin"></span> 🤖 Agente — executa código de verdade</div>
        <div class="rt-steps" id="rt-steps"></div>
      </div>
      <div class="status-line" id="sl"><div class="spinner"></div><span id="st">Pensando...</span></div>
      <div class="stream-text"></div></div></div>`;
    document.getElementById('messages').appendChild(wrap);
    scrollBottom();
    return wrap;
  }

  async function runAgent(text) {
    busy = true; setSending(true);
    const input = document.getElementById('input');
    input.value = ''; input.style.height = 'auto';
    addUserMessage(text);
    const wrap = createAgentMessage();
    const steps = wrap.querySelector('#rt-steps');
    const streamEl = wrap.querySelector('.stream-text');
    let streaming = false;
    currentAbort = new AbortController();

    try {
      const resp = await fetch('/api/agent', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }), signal: currentAbort.signal,
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const ev = JSON.parse(part.slice(6));
          if (ev.type === 'step') {
            const el = document.createElement('div');
            el.className = 'rt-step';
            el.innerHTML = `<span class="rt-ico">${escHtml(ev.icon || '•')}</span><span>${escHtml(ev.message)}</span>`;
            steps.appendChild(el); scrollBottom();
          } else if (ev.type === 'token') {
            if (!streaming) { wrap.querySelector('#sl')?.remove(); streaming = true; }
            streamEl.textContent += ev.content; scrollBottom();
          } else if (ev.type === 'done') {
            wrap.querySelector('#sl')?.remove();
            wrap.querySelector('.stream-text')?.remove();
            wrap.querySelector('#rt')?.classList.add('done');
            const content = wrap.querySelector('.content');
            const md = document.createElement('div');
            md.className = 'md-body';
            md.innerHTML = renderMd(ev.answer || '');
            content.appendChild(md);
            md.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
            scrollBottom(); loadSessions();
          } else if (ev.type === 'error') {
            wrap.querySelector('.content').innerHTML =
              `<div style="color:#f87171;font-size:13px;padding:6px 0">⚠ ${escHtml(ev.message)}</div>`;
          }
        }
      }
    } catch(e) {
      if (e.name !== 'AbortError') wrap.querySelector('.content').innerHTML =
        `<div style="color:#f87171;font-size:13px">Falha: ${escHtml(e.message)}</div>`;
    } finally {
      busy = false; currentAbort = null; setSending(false); input.focus();
    }
  }

  // ── Modo Multi-agente ────────────────────────────────────────
  const _AGENT_LABEL = { researcher:'🔬 Researcher', analyst:'💡 Analyst', coder:'💻 Coder', synthesis:'🔀 Síntese', direct:'⚡ A.P.O.L.O.' };

  async function runMultiAgent(text) {
    busy = true; setSending(true);
    const input = document.getElementById('input');
    input.value = ''; input.style.height = 'auto';
    addUserMessage(text);

    // Monta a bolha do A.P.O.L.O. com container de sub-agentes
    const wrap = document.createElement('div');
    wrap.className = 'message-wrap';
    const ai = document.createElement('div');
    ai.className = 'msg-ai';
    ai.innerHTML = '<div class="avatar">☀️</div>';
    const content = document.createElement('div');
    content.className = 'content';
    // Status de planejamento
    const status = document.createElement('div');
    status.className = 'status-line';
    status.innerHTML = '<div class="spinner"></div><span>Orquestrando equipe de especialistas...</span>';
    content.appendChild(status);
    ai.appendChild(content);
    wrap.appendChild(ai);
    document.getElementById('messages').appendChild(wrap);
    scrollBottom();

    let agentBubbles = {};  // specialist → {el, body}
    let finalAnswer = '';
    currentAbort = new AbortController();

    function getOrCreateBubble(specialist) {
      if (agentBubbles[specialist]) return agentBubbles[specialist];
      const label = _AGENT_LABEL[specialist] || specialist;
      const bubble = document.createElement('div');
      bubble.className = `agent-bubble ${specialist}`;
      const head = document.createElement('div');
      head.className = 'agent-bubble-head';
      head.innerHTML = `<div class="spinner" style="width:10px;height:10px;border-width:1.5px"></div>${escHtml(label)}`;
      const body = document.createElement('div');
      body.className = 'agent-bubble-body';
      bubble.appendChild(head); bubble.appendChild(body);
      content.insertBefore(bubble, content.querySelector('.md-body'));
      agentBubbles[specialist] = { el: bubble, head, body };
      return agentBubbles[specialist];
    }

    try {
      const resp = await fetch('/api/orchestrate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
        signal: currentAbort.signal,
      });
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const ev = JSON.parse(part.slice(6));
          if (ev.type === 'step') {
            status.innerHTML = `<span>${escHtml(ev.icon||'•')} ${escHtml(ev.message)}</span>`;
          } else if (ev.type === 'agent_start') {
            getOrCreateBubble(ev.specialist);
          } else if (ev.type === 'agent_token') {
            const b = getOrCreateBubble(ev.specialist);
            b.body.textContent += ev.content;
            if (ev.specialist === 'synthesis' || ev.specialist === 'direct') finalAnswer += ev.content;
            scrollBottom();
          } else if (ev.type === 'done') {
            // Finaliza: converte corpos dos agentes em Markdown, mostra resposta final
            Object.values(agentBubbles).forEach(b => {
              b.head.querySelector('.spinner')?.remove();
              const md = b.body.textContent;
              b.body.innerHTML = renderMd(md);
              b.body.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
            });
            status.remove();
            if (ev.answer && ev.answer !== finalAnswer) finalAnswer = ev.answer;
            if (ev.specialists_used?.length > 1) {
              // Já renderizado nas bolhas
            } else if (finalAnswer) {
              const md = document.createElement('div');
              md.className = 'md-body';
              md.innerHTML = renderMd(finalAnswer);
              content.appendChild(md);
              md.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
            }
            scrollBottom(); loadSessions();
          } else if (ev.type === 'error') {
            status.innerHTML = `<span style="color:#f87171">⚠ ${escHtml(ev.message)}</span>`;
          }
        }
      }
    } catch(e) {
      if (e.name !== 'AbortError') status.innerHTML =
        `<span style="color:#f87171">Falha: ${escHtml(e.message)}</span>`;
    } finally {
      busy = false; currentAbort = null; setSending(false); input.focus();
    }
  }

  function copyCode(id) {
    const code = document.getElementById(id)?.textContent || '';
    navigator.clipboard.writeText(code).then(() => {
      const btn = document.querySelector(`[onclick="copyCode('${id}')"]`);
      if (!btn) return;
      const orig = btn.textContent;
      btn.textContent = '✓ Copiado';
      setTimeout(()=>btn.textContent=orig, 1500);
    });
  }

  // ── Knowledge backend status (Supabase ou Local SQLite) ─────
  async function checkSupabase() {
    try {
      const [d, h] = await Promise.all([
        fetch('/api/knowledge/stats').then(r=>r.json()),
        fetch('/api/health').then(r=>r.json()).catch(()=>({})),
      ]);
      const dot = document.getElementById('dot-sb');
      const lbl = document.getElementById('lbl-sb');
      const backend = h.knowledge_backend || 'supabase';
      if (d.enabled || d.total >= 0) {
        dot.classList.add('on'); dot.classList.remove('off');
        const backendLabel = backend === 'local_sqlite' ? '💾 Local SQLite' : 'Supabase';
        let txt = `${backendLabel} · ${d.total ?? 0} artigos`;
        if (d.saved_session) txt += ` · ${d.saved_session} salvos`;
        if (d.save_errors) {
          txt += ` · ⚠️ ${d.save_errors} falhas`;
          dot.classList.replace('on','off');
        }
        lbl.textContent = txt;
        if (d.last_error) lbl.title = 'Último erro: ' + d.last_error;
      } else {
        lbl.textContent = 'Base de conhecimento · indisponível';
      }
    } catch {}
  }

  // ── Base de Conhecimento ─────────────────────────────────────
  let kpAllItems = [];
  let kpActiveCat = 'all';

  const CAT_BADGE = {
    official_doc:  ['#0d2a0d','#4ade80','📄'],
    web_search:    ['#0c1828','#60a5fa','🌐'],
    tech_trend:    ['#1a1a0c','#facc15','📡'],
    github:        ['#0d1a0d','#86efac','🐙'],
    synthesis:     ['#1a0d2a','#d8b4fe','🧠'],
    user_question: ['#2a1a0c','#fb923c','💬'],
    self_directed: ['#2a1500','#fbbf24','🎯'],
    user_doc:      ['#10271f','#34d399','📎'],
    encyclopedia:  ['#0c1e2a','#38bdf8','📚'],
    books:         ['#241a0c','#fcd34d','📖'],
  };

  function badgeHtml(cat) {
    const [bg, color, icon] = CAT_BADGE[cat] || ['#1a1a22','#666','•'];
    const label = { official_doc:'Doc', web_search:'Web', tech_trend:'Trend', github:'GitHub', synthesis:'Síntese', user_question:'User', self_directed:'Auto', user_doc:'Arquivo', encyclopedia:'Enciclopédia', books:'Livro' }[cat] || cat;
    return `<span class="kp-badge" style="background:${bg};color:${color}">${icon} ${label}</span>`;
  }

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}) + ' ' + d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
  }

  async function openKnowledge() {
    document.getElementById('knowledge-overlay').classList.add('open');
    lazyLoad('knowledge', loadKnowledgeItems);  // #7
  }

  function closeKnowledge() {
    document.getElementById('knowledge-overlay').classList.remove('open');
  }

  function closeKnowledgeIfBg(e) {
    if (e.target === document.getElementById('knowledge-overlay')) closeKnowledge();
  }

  // ── Mente do A.P.O.L.O. (auto-percepção) ─────────────────────
  async function openMind() {
    document.getElementById('mind-overlay').classList.add('open');
    lazyLoad('mind', loadMind);  // #7
  }
  function closeMind() { document.getElementById('mind-overlay').classList.remove('open'); }
  function closeMindIfBg(e) { if (e.target === document.getElementById('mind-overlay')) closeMind(); }

  // ── Memória pessoal: Sobre mim ───────────────────────────────
  async function openProfile() {
    document.getElementById('profile-overlay').classList.add('open');
    await loadProfile();
    setTimeout(() => document.getElementById('pf-input').focus(), 50);
  }
  function closeProfile() { document.getElementById('profile-overlay').classList.remove('open'); }
  function closeProfileIfBg(e) { if (e.target === document.getElementById('profile-overlay')) closeProfile(); }

  async function loadProfile() {
    const body = document.getElementById('pf-body');
    try {
      const d = await fetch('/api/profile').then(r => r.json());
      const facts = d.facts || [];
      body.innerHTML = facts.length
        ? facts.map(f => `<div class="pf-item"><span>${escHtml(f.fact)}${f.source === 'auto' ? ' <em class="pf-auto" title="Aprendido automaticamente da conversa">auto</em>' : ''}</span><button class="pf-del" onclick="removeFactUI('${f.id}')" title="Esquecer">✕</button></div>`).join('')
        : '<div class="pf-empty">Ainda não sei nada sobre você.<br>Adicione um fato acima, use <code>/remember ...</code> no chat — ou apenas converse, que eu aprendo sozinho.</div>';
    } catch(e) {
      body.innerHTML = `<div class="pf-empty">Erro ao carregar: ${escHtml(e.message)}</div>`;
    }
  }

  async function addFactUI() {
    const inp = document.getElementById('pf-input');
    const fact = inp.value.trim();
    if (!fact) return;
    inp.value = '';
    try {
      await fetch('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fact }) });
      await loadProfile();
    } catch(e) { showIngestToast(`⚠ Falha: ${escHtml(e.message)}`); }
  }

  async function removeFactUI(id) {
    try {
      await fetch('/api/profile/' + encodeURIComponent(id), { method: 'DELETE' });
      await loadProfile();
    } catch(e) { showIngestToast(`⚠ Falha: ${escHtml(e.message)}`); }
  }

  async function rememberFact(fact) {
    try {
      const r = await fetch('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fact }) }).then(x => x.json());
      showIngestToast(r.ok ? `🧠 Anotado sobre você: <b>${escHtml(fact)}</b>` : '⚠ Já sabia disso (ou fato inválido).');
    } catch(e) { showIngestToast(`⚠ Falha: ${escHtml(e.message)}`); }
  }

  async function loadMind() {
    const body = document.getElementById('mind-body');
    body.innerHTML = '<div id="mind-loading">Mapeando a mente do A.P.O.L.O....</div>';
    try {
      const d = await fetch('/api/knowledge/insights').then(r => r.json());
      body.innerHTML = renderMind(d);
      requestAnimationFrame(() => {
        body.querySelectorAll('.mind-bar-fill').forEach(el => { el.style.width = el.dataset.w + '%'; });
      });
    } catch(e) {
      body.innerHTML = `<div class="mind-empty">Erro ao mapear a mente: ${escHtml(e.message)}</div>`;
    }
  }

  // ── Digest "o que aprendi hoje" ──────────────────────────────
  async function digestToday() {
    const body = document.getElementById('mind-body');
    body.innerHTML = '<div id="mind-loading">📅 Montando o resumo de hoje...</div>';
    try {
      const d = await fetch('/api/digest?hours=24').then(r => r.json());
      body.innerHTML = renderDigest(d);
    } catch(e) {
      body.innerHTML = `<div class="mind-empty">Erro ao montar o digest: ${escHtml(e.message)}</div>`;
    }
  }

  function renderDigest(d) {
    if (!d.total) {
      return `<div class="cur-head">Nada novo nas últimas 24h. Ative o ☀️ aprendizado para o A.P.O.L.O. estudar.</div>
              <button class="cur-back" onclick="loadMind()">← Voltar</button>`;
    }
    const secs = (d.sectors || []).map(s => `
      <div class="dg-sector">
        <div class="dg-sector-head">${escHtml(s.label)} <span class="count">${s.count}</span></div>
        <div class="dg-samples">${(s.samples || []).map(t => `<span class="dg-chip">${escHtml(t)}</span>`).join('')}</div>
      </div>`).join('');
    return `
      <div class="cur-head">📅 Nas últimas 24h aprendi <b>${d.total}</b> tópicos novos em <b>${d.sectors.length}</b> setores.</div>
      <div class="cur-actions"><button class="cur-back" onclick="loadMind()">← Voltar</button></div>
      ${secs}`;
  }

  // ── Memória episódica: reindexar conversas antigas ──────────
  async function reindexEpisodic() {
    const btn = document.getElementById('mind-reindex');
    const orig = btn.textContent;
    btn.textContent = '⏳ Indexando...';
    btn.disabled = true;
    try {
      const d = await fetch('/api/sessions/reindex', {method:'POST'}).then(r => r.json());
      if (d.ok) {
        btn.textContent = `✓ ${d.indexed} indexadas`;
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
      } else {
        btn.textContent = '✗ Erro';
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
      }
    } catch(e) {
      btn.textContent = orig;
      btn.disabled = false;
    }
  }

  // ── Memória de Projeto ───────────────────────────────────────
  async function analyzeCurrentProject() {
    const btn = document.getElementById('coder-analyze-btn');
    const orig = btn.textContent;
    btn.textContent = '⏳ Analisando...';
    btn.disabled = true;
    try {
      const d = await fetch('/api/project/analyze', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path: ''}),  // usa workspace atual do Coder
      }).then(r => r.json());
      if (d.ok) {
        updateProjectIndicator(d.context);
        btn.textContent = `✓ ${d.context.name}`;
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
        showIngestToast(`🎯 Projeto <b>${escHtml(d.context.name)}</b> memorizado — stack: ${escHtml(d.context.stack || '—')}`);
      } else {
        btn.textContent = '✗ Erro'; btn.disabled = false;
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
      }
    } catch(e) {
      btn.textContent = orig; btn.disabled = false;
    }
  }

  function updateProjectIndicator(ctx) {
    const ind = document.getElementById('project-indicator');
    if (!ctx) { ind.style.display = 'none'; return; }
    document.getElementById('project-name').textContent = ctx.name || '';
    document.getElementById('project-stack').textContent = ctx.stack ? '· ' + ctx.stack : '';
    ind.style.display = 'flex';
  }

  async function clearProjectContext() {
    await fetch('/api/project/clear', {method:'POST'});
    document.getElementById('project-indicator').style.display = 'none';
    showIngestToast('Contexto de projeto removido');
  }

  async function loadProjectContext() {
    try {
      const d = await fetch('/api/project/context').then(r => r.json());
      updateProjectIndicator(d.active);
    } catch {}
  }

  // ── Analisar Repositório GitHub ───────────────────────────────
  async function openRepoModal() {
    document.getElementById('repo-modal').style.display = 'flex';
    document.getElementById('repo-progress').style.display = 'none';
    document.getElementById('repo-steps').innerHTML = '';
    document.getElementById('repo-progress-bar').style.width = '0%';
    document.getElementById('repo-indexed-list').style.display = 'none';
    // Carrega repos já indexados
    try {
      const d = await fetch('/api/repo/list').then(r => r.json());
      if (d.repos && d.repos.length) _renderIndexedRepos(d.repos);
    } catch {}
    setTimeout(() => document.getElementById('repo-url-input').focus(), 100);
  }

  function closeRepoModal() {
    document.getElementById('repo-modal').style.display = 'none';
  }

  function _renderIndexedRepos(repos) {
    const list = document.getElementById('repo-indexed-list');
    const items = document.getElementById('repo-indexed-items');
    items.innerHTML = repos.map(r => `
      <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:#0a1f0a;border:1px solid #1a3a1a;border-radius:7px">
        <span style="font-size:13px">🐙</span>
        <div style="flex:1;min-width:0">
          <div style="font-size:12px;font-weight:600;color:#4ade80">${escHtml(r.name)}</div>
          <div style="font-size:10px;color:#555">${r.files} arquivo(s) indexado(s)</div>
        </div>
        <button onclick="askAboutRepo('${escHtml(r.name)}')"
                style="background:none;border:1px solid #1a3a1a;color:#4ade80;padding:3px 9px;border-radius:5px;cursor:pointer;font-size:10.5px;white-space:nowrap">
          Perguntar →
        </button>
      </div>`).join('');
    list.style.display = 'block';
  }

  function askAboutRepo(repoName) {
    closeRepoModal();
    document.getElementById('input').value = `Sobre o repositório ${repoName}: `;
    document.getElementById('input').focus();
  }

  function _addRepoStep(icon, msg, color) {
    const el = document.createElement('div');
    el.style.cssText = `display:flex;gap:7px;align-items:flex-start;color:${color||'#aaa'}`;
    el.innerHTML = `<span style="flex-shrink:0">${escHtml(icon)}</span><span>${escHtml(msg)}</span>`;
    const steps = document.getElementById('repo-steps');
    steps.appendChild(el);
    steps.scrollTop = steps.scrollHeight;
  }

  async function startRepoAnalysis() {
    const url = document.getElementById('repo-url-input').value.trim();
    if (!url) return;
    const btn = document.getElementById('repo-analyze-btn');
    const cancelBtn = document.getElementById('repo-cancel-btn');
    btn.disabled = true; btn.textContent = '⏳ Analisando...';
    cancelBtn.textContent = 'Fechar';

    const progress = document.getElementById('repo-progress');
    const progressBar = document.getElementById('repo-progress-bar');
    const steps = document.getElementById('repo-steps');
    progress.style.display = 'block';
    steps.innerHTML = '';
    progressBar.style.width = '0%';

    try {
      const resp = await fetch('/api/repo/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url}),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = '';

      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {stream: true});
        const parts = buf.split('\n\n'); buf = parts.pop();

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const ev = JSON.parse(part.slice(6));

          if (ev.type === 'step') {
            _addRepoStep(ev.icon || '•', ev.message, '#aaa');
          } else if (ev.type === 'progress') {
            const pct = Math.round((ev.current / ev.total) * 100);
            progressBar.style.width = pct + '%';
            // Atualiza última linha de progresso (não adiciona nova a cada arquivo)
            const existing = steps.querySelector('.prog-line');
            const msg = `${ev.current}/${ev.total} — ${ev.file}`;
            if (existing) { existing.querySelector('span:last-child').textContent = msg; }
            else {
              const el = document.createElement('div');
              el.className = 'prog-line';
              el.style.cssText = 'display:flex;gap:7px;align-items:flex-start;color:#888';
              el.innerHTML = `<span style="flex-shrink:0">📄</span><span>${escHtml(msg)}</span>`;
              steps.appendChild(el);
              steps.scrollTop = steps.scrollHeight;
            }
          } else if (ev.type === 'done') {
            progressBar.style.width = '100%';
            progressBar.style.background = '#4ade80';
            _addRepoStep('✅',
              `Concluído! ${ev.files_indexed} arquivo(s), ${ev.chunks_total} chunk(s) indexados.`,
              '#4ade80');
            // Recarrega lista de repos
            try {
              const d = await fetch('/api/repo/list').then(r => r.json());
              if (d.repos && d.repos.length) _renderIndexedRepos(d.repos);
            } catch {}
            // Sugere uma pergunta
            setTimeout(() => {
              if (ev.repo_name) {
                const hint = `O que esse repositório faz? Me dê um resumo do ${escHtml(ev.repo_name)}`;
                document.getElementById('input').value = hint;
              }
              closeRepoModal();
            }, 2000);
          } else if (ev.type === 'error') {
            progressBar.style.background = '#f87171';
            _addRepoStep('❌', ev.message, '#f87171');
          }
        }
      }
    } catch(e) {
      _addRepoStep('❌', 'Erro: ' + e.message, '#f87171');
    } finally {
      btn.disabled = false; btn.textContent = '🐙 Analisar';
    }
  }

  // ── Importação de pasta Obsidian ─────────────────────────────
  function openObsidianImport() {
    document.getElementById('obsidian-modal').style.display = 'flex';
    document.getElementById('obs-result').style.display = 'none';
    document.getElementById('obs-status').textContent = '';
    setTimeout(() => document.getElementById('obs-path').focus(), 100);
  }
  function closeObsidianImport() {
    document.getElementById('obsidian-modal').style.display = 'none';
  }
  async function doObsidianImport() {
    const path = document.getElementById('obs-path').value.trim();
    if (!path) { document.getElementById('obs-status').textContent = '⚠ Informe o caminho.'; return; }
    const btn = document.getElementById('obs-import-btn');
    const status = document.getElementById('obs-status');
    const result = document.getElementById('obs-result');
    btn.disabled = true; btn.textContent = '⏳ Importando...';
    status.textContent = 'Lendo arquivos...'; result.style.display = 'none';
    try {
      const d = await fetch('/api/ingest/folder', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ path }),
      }).then(r => r.json());
      if (d.ok) {
        status.textContent = '';
        result.style.display = 'block';
        result.innerHTML = `
          <div style="color:#4ade80;font-weight:600;margin-bottom:8px">✅ Importação concluída!</div>
          <div>📂 Pasta: <code style="background:#1e1e28;padding:1px 5px;border-radius:3px">${escHtml(d.folder)}</code></div>
          <div>📄 Arquivos encontrados: <b>${d.total_files}</b></div>
          <div>✅ Ingeridos com sucesso: <b style="color:#4ade80">${d.ingested}</b></div>
          ${d.skipped ? `<div>⚠️ Ignorados (vazios/erro): ${d.skipped}</div>` : ''}
          <div style="margin-top:10px;color:#888;font-size:11px">O A.P.O.L.O. já pode responder sobre o conteúdo desses arquivos e citá-los nas respostas.</div>
        `;
        // Atualiza contador da base
        const kc = document.getElementById('kb-count');
        kc.textContent = (parseInt(kc.textContent)||0) + d.ingested;
      } else {
        status.textContent = ''; result.style.display = 'block';
        result.innerHTML = `<div style="color:#f87171">❌ ${escHtml(d.error || 'Falha ao importar.')}</div>`;
      }
    } catch(e) {
      status.textContent = ''; result.style.display = 'block';
      result.innerHTML = `<div style="color:#f87171">❌ Erro: ${escHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = '📥 Importar';
    }
  }

  // ── Exportação para Obsidian ──────────────────────────────────
  async function exportObsidian() {
    const btn = document.getElementById('mind-obsidian');
    const orig = btn.textContent;
    btn.textContent = '⏳ Gerando...';
    btn.disabled = true;
    try {
      const resp = await fetch('/api/export/obsidian');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      // Extrai nome do arquivo do header Content-Disposition
      const cd = resp.headers.get('Content-Disposition') || '';
      const match = cd.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : 'APOLO_Obsidian.zip';
      // Download automático
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      btn.textContent = '✓ Baixado!';
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
    } catch(e) {
      btn.textContent = '✗ Erro';
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
    }
  }

  // ── Reparo de sínteses cruas (timeouts antigos) ───────────────
  async function repairSummaries() {
    const btn = document.getElementById('mind-repair');
    const orig = btn.textContent;
    btn.disabled = true; btn.textContent = '🩹 Verificando…';
    try {
      const d = await fetch('/api/learning/repair', {method:'POST'}).then(r => r.json());
      if (!d.ok) { btn.textContent = '✗ ' + (d.error || 'erro'); }
      else if (!d.found) { btn.textContent = '✨ Nada cru'; }
      else {
        btn.textContent = `🩹 Reparando ${d.started}/${d.found}…`;
        alert(`🩹 Encontrei ${d.found} síntese(s) crua(s) — re-sintetizando ${d.started} em segundo plano.\nO resultado chega nas 🔔 notificações. Rode de novo para reparar as demais.`);
      }
    } catch(e) { btn.textContent = '✗ Erro'; }
    setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 4000);
  }

  // ── Curador de Memória (dedup) ───────────────────────────────
  async function curateMemory() {
    const body = document.getElementById('mind-body');
    body.innerHTML = '<div id="mind-loading">🧹 Procurando conhecimento duplicado...</div>';
    try {
      const d = await fetch('/api/curate/scan').then(r => r.json());
      body.innerHTML = renderCuration(d);
    } catch(e) {
      body.innerHTML = `<div class="mind-empty">Erro ao escanear: ${escHtml(e.message)}</div>`;
    }
  }

  function renderCuration(d) {
    const chroma = d.chroma_duplicates || 0;
    const log = d.log_duplicates || 0;
    const extras = [];
    if (chroma) extras.push(`${chroma} no índice de recall`);
    if (log) extras.push(`${log} re-estudos no log`);
    const extraNote = extras.length ? ` <span class="cur-chroma">+ ${extras.join(' e ')} serão limpos junto.</span>` : '';
    if (!d.removable) {
      if (chroma || log) {
        return `<div class="cur-head">A base está sem duplicatas, mas há <b>${chroma + log} repetição(ões)</b> (${extras.join(' e ')}).</div>
          <div class="cur-actions">
            <button class="cur-remove" onclick='applyCuration([])'>🧹 Limpar repetições (${chroma + log})</button>
            <button class="cur-back" onclick="loadMind()">← Voltar</button>
          </div>`;
      }
      return `<div class="cur-head">✨ <b>Memória limpa!</b> Nenhuma duplicata encontrada em ${d.total} conhecimentos.</div>
              <button class="cur-back" onclick="loadMind()">← Voltar</button>`;
    }
    const allIds = [];
    const clusters = d.clusters.map(c => {
      c.dupes.forEach(dp => allIds.push(dp.id));
      return `<div class="cur-cluster">
        <div class="cur-keep" title="${escHtml(c.keeper.title||'')}">✅ manter: ${escHtml(c.keeper.title||'—')}</div>
        ${c.dupes.map(dp => `<div class="cur-dup" title="${escHtml(dp.title||'')}">✕ remover: ${escHtml(dp.title||'—')}</div>`).join('')}
      </div>`;
    }).join('');
    return `
      <div class="cur-head">🧹 <b>${d.removable} duplicata(s)</b> em ${d.duplicate_clusters} grupo(s), de ${d.total} conhecimentos — mantenho o mais completo de cada grupo.${extraNote}</div>
      <div class="cur-actions">
        <button class="cur-remove" onclick='applyCuration(${JSON.stringify(allIds)})'>🗑️ Remover ${d.removable} duplicata(s)</button>
        <button class="cur-back" onclick="loadMind()">← Voltar</button>
      </div>
      ${clusters}`;
  }

  async function applyCuration(ids) {
    ids = ids || [];
    const msg = ids.length
      ? `Remover ${ids.length} duplicata(s) da base + limpar o índice de recall? Esta ação não pode ser desfeita.`
      : `Limpar os trechos repetidos do índice de recall? Esta ação não pode ser desfeita.`;
    if (!confirm(msg)) return;
    try {
      const r = await fetch('/api/curate/apply', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
      }).then(x => x.json());
      showIngestToast(`✅ Limpeza: ${r.removed || 0} da base + ${r.chroma_pruned || 0} do recall + ${r.log_pruned || 0} do log.`);
      await loadMind();
    } catch(e) {
      showIngestToast(`⚠ Falha ao remover: ${escHtml(e.message)}`);
    }
  }

  const SECTOR_LABELS = {
    backend_apis:'⚙️ Backend & APIs', frontend_web:'🎨 Frontend & Web', mobile:'📱 Mobile',
    data_ml:'🤖 Data & ML', systems_languages:'🦀 Sistemas & Linguagens', devops_cloud:'☁️ DevOps & Cloud',
    databases:'🗄️ Bancos de Dados', security:'🔐 Segurança', ai_agents:'🧠 Agentes de IA',
    game_dev:'🎮 Game Dev', blockchain_web3:'⛓️ Blockchain & Web3', cs_fundamentals:'📐 Fundamentos de CS',
    science:'🔬 Ciência', finance_economics:'💰 Finanças & Economia', productivity_learning:'⏱️ Produtividade',
    communication_languages:'🗣️ Comunicação & Idiomas', design_ux:'✏️ Design & UX',
    business_product:'📈 Negócios & Produto', health_mind:'🧬 Saúde & Mente',
    history_philosophy:'📜 História & Filosofia', data_engineering:'🛠️ Data Engineering',
    sre_reliability:'🚨 SRE & Confiabilidade', embedded_iot:'🔌 Embarcados & IoT',
    graphics_xr:'🕶️ Gráficos & XR', mathematics:'➗ Matemática', career_growth:'🚀 Carreira',
    law_compliance:'⚖️ Direito & Compliance', arts_creativity:'🎭 Artes & Criatividade',
    medicine_health:'🩺 Medicina & Saúde', psychology:'💭 Psicologia', education_pedagogy:'🎓 Educação',
    environment_sustainability:'🌱 Meio Ambiente', cooking_nutrition:'🍳 Culinária & Nutrição',
    space_astronomy:'🪐 Astronomia', geography_geopolitics:'🗺️ Geografia & Geopolítica',
    marketing_sales:'📣 Marketing & Vendas', sports_fitness:'🏋️ Esportes & Fitness',
    engineering_physical:'🏗️ Engenharia (Física)', networking_protocols:'🛰️ Redes & Protocolos',
    testing_qa:'🧪 Testes & QA', quantum_computing:'⚛️ Computação Quântica',
    robotics_automation:'🦾 Robótica & Automação', investing_markets:'💹 Investimentos & Mercado',
    crypto_finance:'🪙 Cripto & DeFi', accounting_tax:'🧾 Contabilidade & Impostos',
    macroeconomics:'🏦 Macroeconomia', pharmacology:'💊 Farmacologia', public_health:'🏥 Saúde Pública',
    biotech_genomics:'🧫 Biotecnologia & Genômica', politics_government:'🏛️ Política & Governo',
    languages_learning:'🗨️ Idiomas', agriculture_food:'🌾 Agricultura & Alimentos',
    outros:'📦 Outros',
  };

  function renderMind(d) {
    const L = d.learning || {};
    const total  = d.total || 0;
    const cats   = d.categories || [];
    const secs   = d.sectors || [];
    const doms   = d.domains || [];
    const recent = d.recent || [];
    const maxCat = Math.max(1, ...cats.map(c => c.count));
    const maxSec = Math.max(1, ...secs.map(s => s.count));
    const secLabel = (k) => SECTOR_LABELS[k] || k;

    const liveDot = `<span class="mind-live-dot ${L.running ? 'on' : ''}"></span>`;
    const hero = `
      <div class="mind-hero">
        <div class="mind-stat"><div class="num">${total}</div><div class="lbl">Conhecimentos</div></div>
        <div class="mind-stat"><div class="num">${L.total_learned ?? 0}</div><div class="lbl">Tópicos estudados</div></div>
        <div class="mind-stat"><div class="num">${L.self_directed_count ?? 0}</div><div class="lbl">🎯 Auto-currículo</div></div>
        <div class="mind-stat"><div class="num">${liveDot}${L.running ? 'ON' : 'OFF'}</div><div class="lbl">Aprendizado</div></div>
      </div>`;

    if (!d.enabled) {
      return hero + '<div class="mind-empty" style="text-align:center;padding:24px 0">Supabase não configurado — a base de conhecimento persistente está desativada.</div>';
    }

    const tl = d.timeline || [];
    const maxDay = Math.max(1, ...tl.map(p => p.count));
    const tlTotal = tl.reduce((a, p) => a + p.count, 0);
    const timelineSection = tl.length ? `
      <div class="mind-section">
        <h3>📈 Crescimento (14 dias) <span class="count">${tlTotal} aprendidos</span></h3>
        <div class="mind-timeline">
          ${tl.map(p => `<div class="mtl-col" title="${p.date}: ${p.count}"><div class="mtl-bar" style="height:${Math.round(p.count / maxDay * 100)}%"></div></div>`).join('')}
        </div>
      </div>` : '';

    const secSection = secs.length ? `
      <div class="mind-section">
        <h3>🗂️ Conhecimento por setor <span class="count">${secs.length} setores</span></h3>
        ${secs.map(s => `
          <div class="mind-bar-row">
            <div class="mind-bar-label wide" title="${escHtml(secLabel(s.name))}">${escHtml(secLabel(s.name))}</div>
            <div class="mind-bar-track"><div class="mind-bar-fill" data-w="${Math.round(s.count / maxSec * 100)}" style="width:0%"></div></div>
            <div class="mind-bar-num">${s.count}</div>
          </div>`).join('')}
      </div>` : '';

    const catSection = cats.length ? `
      <div class="mind-section">
        <h3>📂 Conhecimento por categoria <span class="count">${cats.length} tipos</span></h3>
        ${cats.map(c => `
          <div class="mind-bar-row">
            <div class="mind-bar-label">${badgeHtml(c.name)}</div>
            <div class="mind-bar-track"><div class="mind-bar-fill" data-w="${Math.round(c.count / maxCat * 100)}" style="width:0%"></div></div>
            <div class="mind-bar-num">${c.count}</div>
          </div>`).join('')}
      </div>` : '';

    const domSection = doms.length ? `
      <div class="mind-section">
        <h3>🌐 Principais fontes</h3>
        <div class="mind-chips">
          ${doms.map(dm => `<span class="mind-chip">${escHtml(dm.name)} <b>${dm.count}</b></span>`).join('')}
        </div>
      </div>` : '';

    const next = (L.next_studies || []).slice(0, 6);
    const nextSection = next.length ? `
      <div class="mind-section">
        <h3>🎯 Próximos estudos auto-dirigidos</h3>
        ${next.map(s => `<div class="mind-study">${escHtml(s)}</div>`).join('')}
      </div>` : '';

    const gaps = (L.recent_gaps || []).slice(0, 6);
    const gapsSection = gaps.length ? `
      <div class="mind-section">
        <h3>🕳️ Lacunas detectadas no chat <span class="count">${L.gap_count || gaps.length} no total</span></h3>
        ${gaps.map(g => `<div class="mind-study">${escHtml(g)}</div>`).join('')}
      </div>` : '';

    const recentSection = `
      <div class="mind-section">
        <h3>🕐 Aprendido recentemente</h3>
        ${recent.length ? recent.map(r => `
          <div class="mind-recent-item">
            ${badgeHtml(r.category)}
            <span class="mind-recent-title">${escHtml(r.title)}</span>
            <span class="mind-recent-date">${escHtml(formatDate(r.updated_at))}</span>
          </div>`).join('') : '<div class="mind-empty">Ainda nada salvo na base. Ative o aprendizado para começar.</div>'}
      </div>`;

    return hero + timelineSection + secSection + catSection + domSection + nextSection + gapsSection + recentSection;
  }

  async function loadKnowledgeItems() {
    const body = document.getElementById('kp-body');
    body.innerHTML = '<div id="kp-loading">Carregando conhecimento...</div>';
    try {
      const data = await fetch('/api/learning/history?limit=200').then(r => r.json());
      kpAllItems = data;
      document.getElementById('kb-count').textContent = data.length;
      document.getElementById('kp-stats').textContent = `${data.length} tópicos aprendidos`;
      populateSectorFilter(data);
      renderKnowledgeItems();
    } catch(e) {
      body.innerHTML = `<div id="kp-empty">Erro ao carregar: ${escHtml(e.message)}</div>`;
    }
  }

  function setCatFilter(cat) {
    kpActiveCat = cat;
    document.querySelectorAll('.kp-filter').forEach(b => {
      b.classList.toggle('on', b.dataset.cat === cat);
    });
    renderKnowledgeItems();
  }

  function populateSectorFilter(items) {
    const sel = document.getElementById('kp-sector');
    if (!sel) return;
    const counts = {};
    items.forEach(i => { const s = i.sector || 'outros'; counts[s] = (counts[s] || 0) + 1; });
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const cur = sel.value || 'all';
    sel.innerHTML = '<option value="all">🗂️ Todos os setores</option>' +
      sorted.map(([s, n]) => `<option value="${s}">${(SECTOR_LABELS[s] || s)} (${n})</option>`).join('');
    sel.value = cur;
  }

  function filterKnowledge() { renderKnowledgeItems(); }

  function renderKnowledgeItems() {
    const body = document.getElementById('kp-body');
    const q = document.getElementById('kp-search').value.toLowerCase().trim();

    const sec = document.getElementById('kp-sector')?.value || 'all';
    let items = kpAllItems;
    if (kpActiveCat !== 'all') items = items.filter(i => i.category === kpActiveCat);
    if (sec !== 'all') items = items.filter(i => (i.sector || 'outros') === sec);
    if (q) items = items.filter(i =>
      i.topic?.toLowerCase().includes(q) ||
      i.summary?.toLowerCase().includes(q) ||
      i.url?.toLowerCase().includes(q)
    );

    if (!items.length) {
      body.innerHTML = '<div id="kp-empty">Nenhum resultado encontrado.<br><small style="color:#2a2a2a">Ative o modo aprendizado para A.P.O.L.O. começar a estudar.</small></div>';
      return;
    }

    body.innerHTML = items.map((item, i) => {
      const title = item.topic.replace(/^\[(A\.P\.O\.L\.O\.|Apolo Study|Auto|Tendência|GitHub Trending:)\s*/,'').replace(/\]\s*/,'');
      const date  = formatDate(item.studied_at);
      const hasSum = item.summary && item.summary.length > 50;
      return `
        <div class="kp-item" id="kpi-${i}">
          <div class="kp-item-header" onclick="toggleKpItem(${i})">
            ${badgeHtml(item.category)}
            <span class="kp-title">${escHtml(title)}</span>
            <span class="kp-meta">${escHtml(date)}</span>
            ${hasSum ? '<span class="kp-chevron">▼</span>' : ''}
            <span class="kp-forget" title="Esquecer este conhecimento" onclick="event.stopPropagation();forgetKnowledge(${item.id||0}, this)" style="cursor:pointer;color:#5a5a66;padding:0 4px">🗑️</span>
          </div>
          ${hasSum ? `
          <div class="kp-summary">
            ${item.url && !item.url.startsWith('synthesis://') ? `<div class="kp-url">🔗 <a href="${escHtml(item.url)}" target="_blank" rel="noopener">${escHtml(item.url)}</a></div>` : ''}
            <div class="kp-md">${renderMd(item.summary)}</div>
          </div>` : ''}
        </div>`;
    }).join('');

    body.querySelectorAll('.kp-md pre code').forEach(el => {
      try { hljs.highlightElement(el); } catch {}
    });
  }

  async function forgetKnowledge(id, el) {
    if (!id) return;
    if (!confirm('Esquecer este conhecimento? Ele será removido da memória (log, base e índice).')) return;
    try {
      const r = await fetch('/api/knowledge/forget', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id})}).then(r=>r.json());
      if (r.ok) {
        const item = el.closest('.kp-item');
        if (item) { item.style.transition='opacity .2s'; item.style.opacity='0'; setTimeout(()=>item.remove(), 200); }
      } else alert('Não foi possível esquecer: ' + (r.error||''));
    } catch { alert('Falha ao esquecer'); }
  }

  function toggleKpItem(i) {
    const el = document.getElementById('kpi-' + i);
    if (!el) return;
    const wasOpen = el.classList.contains('expanded');
    document.querySelectorAll('.kp-item.expanded').forEach(x => x.classList.remove('expanded'));
    if (!wasOpen) el.classList.add('expanded');
  }

  // ── Code Review ──────────────────────────────────────────────
  let reviewBusy = false;

  function openReview() {
    document.getElementById('review-overlay').classList.add('open');
    setTimeout(() => document.getElementById('rv-code').focus(), 50);
  }
  function closeReview() {
    document.getElementById('review-overlay').classList.remove('open');
  }
  function closeReviewIfBg(e) {
    if (e.target === document.getElementById('review-overlay')) closeReview();
  }

  async function runReview() {
    if (reviewBusy) return;
    const code = document.getElementById('rv-code').value.trim();
    const language = document.getElementById('rv-lang').value;
    if (code.length < 10) {
      document.getElementById('rv-result').innerHTML = '<div style="color:#f87171;font-size:13px">Cole um trecho de código maior para revisar.</div>';
      return;
    }
    reviewBusy = true;
    const runBtn = document.getElementById('rv-run');
    runBtn.disabled = true; runBtn.textContent = '⏳ Revisando...';
    const result = document.getElementById('rv-result');
    result.innerHTML = `<div class="rv-status" id="rv-st"><div class="spinner"></div><span>Iniciando revisão...</span></div><div class="rv-stream"></div>`;
    const streamEl = result.querySelector('.rv-stream');
    let streaming = false, sources = [];

    try {
      const resp = await fetch('/api/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, language }),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop();
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const ev = JSON.parse(part.slice(6));
          if (ev.type === 'status') {
            const st = result.querySelector('#rv-st span');
            if (st) st.textContent = ev.message;
          } else if (ev.type === 'token') {
            if (!streaming) { result.querySelector('#rv-st')?.remove(); streaming = true; }
            streamEl.textContent += ev.content;
            streamEl.scrollIntoView({ block: 'end' });
          } else if (ev.type === 'done') {
            sources = ev.sources || [];
            result.querySelector('#rv-st')?.remove();
            streamEl.remove();
            const md = document.createElement('div');
            md.className = 'rv-md';
            md.innerHTML = renderMd(ev.review || '');
            result.appendChild(md);
            md.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
            const cited = sources.filter(s => s.title);
            if (cited.length) {
              const sd = document.createElement('div');
              sd.className = 'rv-sources';
              sd.innerHTML = `<b>📚 Apoiado em ${cited.length} memória(s) do A.P.O.L.O.:</b> ` +
                cited.map(s => escHtml(s.title)).join(' · ');
              result.appendChild(sd);
            }
          } else if (ev.type === 'error') {
            result.innerHTML = `<div style="color:#f87171;font-size:13px">⚠ ${escHtml(ev.message)}</div>`;
          }
        }
      }
    } catch(e) {
      result.innerHTML = `<div style="color:#f87171;font-size:13px">Falha: ${escHtml(e.message)}</div>`;
    }
    reviewBusy = false;
    runBtn.disabled = false; runBtn.textContent = '▶ Revisar';
  }

  // Fecha com ESC (conhecimento, review ou mente)
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeKnowledge(); closeReview(); closeMind(); closeProfile(); }
  });

  // ── Modelos: mostra o modelo de chat ativo + dica de velocidade ──
  async function loadModelInfo() {
    try {
      const m = await fetch('/api/models').then(r => r.json());
      if (m.chat_model) {
        document.getElementById('cap-model').textContent = `${m.chat_model} · chat · Ollama local`;
      }
      visionAvailable = !!m.has_vision;
      const ib = document.getElementById('image-btn');
      if (ib) ib.title = visionAvailable
        ? `Analisar uma imagem/print com ${m.vision_model}`
        : 'Analisar imagens — baixe um modelo de visão: ollama pull llava';
      if (m.suggestion) {
        const hint = document.getElementById('speed-hint');
        document.getElementById('speed-cmd').textContent = `ollama pull ${m.suggestion}`;
        hint.style.display = 'block';
        hint.onclick = () => {
          navigator.clipboard?.writeText(`ollama pull ${m.suggestion}`).catch(()=>{});
          const note = hint.querySelector('.sh-note');
          const prev = note.textContent;
          note.textContent = '✓ Comando copiado! Cole no terminal e rode.';
          setTimeout(() => { note.textContent = prev; }, 2500);
        };
      }
    } catch {}
  }

  // ── Boot consolidado ─────────────────────────────────────────
  _initTabs();      // #10 inicializa/restaura as abas antes do boot
  restoreSession();
  bootLoad();
  // #6 SSE push mantém o painel de aprendizado vivo. refreshLearnStatus() faz o
  // bootstrap imediato (não espera o 1º tick do SSE e cobre navegadores sem
  // EventSource); startLearnSSE() assume os updates ao vivo em seguida.
  refreshLearnStatus();
  startLearnSSE();
  // ── Temas ─────────────────────────────────────────────────────
  const _THEMES = ['dark', 'light', 'midnight'];
  const _THEME_ICONS = { dark: '🌙', light: '☀️', midnight: '🔮' };
  let _currentTheme = localStorage.getItem('apolo-theme') || 'dark';

  function applyTheme(t) {
    _currentTheme = t;
    document.documentElement.setAttribute('data-theme', t === 'dark' ? '' : t);
    const btn = document.getElementById('theme-btn');
    if (btn) btn.textContent = _THEME_ICONS[t] || '🌙';
    localStorage.setItem('apolo-theme', t);
  }
  function cycleTheme() {
    const next = _THEMES[(_THEMES.indexOf(_currentTheme) + 1) % _THEMES.length];
    applyTheme(next);
    showIngestToast(`Tema: ${next === 'dark' ? 'Escuro' : next === 'light' ? 'Claro' : 'Midnight'}`);
  }
  applyTheme(_currentTheme);  // aplica o tema salvo no boot

  // ── Boot consolidado (/api/boot) ──────────────────────────────
  // Uma única chamada substitui: /api/models + /api/knowledge/stats +
  // /api/learning/status + /api/notifications + /api/sessions
  async function bootLoad() {
    try {
      const d = await fetch('/api/boot').then(r => r.json());
      // Modelos
      if (d.models) {
        const m = d.models;
        document.getElementById('cap-model').textContent =
          `${m.chat_model || m.heavy_model} · Ollama local`;
        if (m.chat_model && m.chat_model !== m.heavy_model) {
          const hint = document.getElementById('speed-hint');
          if (hint) hint.style.display = 'none';
        }
      }
      // Knowledge stats
      if (d.knowledge) {
        const kb = d.knowledge;
        const dot = document.getElementById('dot-sb');
        const lbl = document.getElementById('lbl-sb');
        if (dot && lbl) {
          if (kb.enabled || kb.total >= 0) {
            dot.className = 'dot on';
            lbl.textContent = `${kb.total ?? 0} artigos`;
          }
        }
        const kc = document.getElementById('kb-count');
        if (kc) kc.textContent = kb.total ?? 0;
      }
      // Sessions
      if (d.sessions && d.sessions.length) {
        renderSessions(d.sessions);
      }
      // Notificações
      if (d.unread_notifications > 0) {
        const badge = document.getElementById('bell-badge');
        if (badge) { badge.textContent = d.unread_notifications; badge.classList.add('show'); }
      }
      // Projeto ativo
      if (d.active_project) updateProjectIndicator(d.active_project);
    } catch {
      // Fallback: chamadas individuais se /api/boot falhar
      loadSessions();
      checkSupabase();
    }
  }

  startNotifications();
  loadProjectContext();   // exibe indicador de projeto ativo no rodapé do input
  // Atualiza contador da knowledge base no boot
  fetch('/api/learning/history').then(r=>r.json()).then(d => {
    if (d.length) document.getElementById('kb-count').textContent = d.length;
  }).catch(()=>{});
