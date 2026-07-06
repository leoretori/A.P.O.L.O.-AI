// ════ MELHORIAS VISUAIS E DE DESEMPENHO (#1–#10) ═════════════════════════════

// #2 Indicador de digitação
function createTypingIndicator() {
  const d = document.createElement('div');
  d.className = 'typing-dots'; d.style.cssText = 'padding:4px 0';
  d.innerHTML = '<span></span><span></span><span></span>'; return d;
}

// #3 + #7 Reações nas respostas (localStorage + API para métricas)
function buildReactionBar(text, memorySources) {
  const bar = document.createElement('div'); bar.className = 'reaction-bar';
  const key = 'rxn_' + Math.abs([...text.slice(0,60)].reduce((h,c)=>Math.imul(31,h)+c.charCodeAt(0)|0,0)).toString(36);
  const stored = localStorage.getItem(key);
  ['👍','👎'].forEach((emoji, idx) => {
    const btn = document.createElement('button');
    btn.className = 'reaction-btn' + (stored===emoji ? (idx===0?' active':' active down') : '');
    btn.textContent = emoji;
    btn.title = idx===0 ? 'Boa resposta' : 'Resposta ruim';
    btn.onclick = () => {
      const r = stored===emoji ? '' : emoji;
      localStorage.setItem(key, r);
      if (r) {
        // #7 Persiste no servidor para métricas de qualidade
        const reaction = r === '👍' ? 'up' : 'down';
        const srcs = (memorySources||[]).map(s=>s.url).filter(Boolean);
        fetch('/api/reactions', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({message_hash: key, reaction, session_id: sessionId, sources: srcs})
        }).catch(()=>{});
      }
      bar.replaceWith(buildReactionBar(text, memorySources));
    };
    bar.appendChild(btn);
  });
  return bar;
}

// #4 Copy on hover em qualquer bloco de código
function addInlineCopyButtons(container) {
  container.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.inline-copy')) return;
    const code = pre.querySelector('code'); if (!code) return;
    const btn = document.createElement('button'); btn.className = 'inline-copy'; btn.textContent = 'Copiar';
    btn.onclick = e => { e.stopPropagation(); navigator.clipboard.writeText(code.textContent||'').catch(()=>{}); btn.textContent='✓'; setTimeout(()=>btn.textContent='Copiar',1400); };
    pre.appendChild(btn);
  });
}

// #5 Números de linha no viewer do Coder
function addLineNumbers(preEl) {
  const code = preEl.querySelector('code');
  if (!code || preEl.querySelector('.ln-nums')) return;
  const lines = code.innerHTML.split('\n'); if (lines.length < 3) return;
  const gutter = document.createElement('div'); gutter.className = 'ln-nums';
  gutter.style.cssText = 'float:left;min-width:2.5ch;text-align:right;padding:14px 10px 14px 12px;color:#333;font-size:11.5px;line-height:1.55;user-select:none;font-family:ui-monospace,monospace;border-right:1px solid #1e1e26;margin-right:12px';
  gutter.innerHTML = lines.map((_,i)=>`<div>${i+1}</div>`).join('');
  preEl.style.cssText += ';display:flex;padding:0';
  preEl.insertBefore(gutter, code);
  code.style.cssText += ';padding:14px 12px 14px 0;flex:1';
}

// #6 SSE push para status de aprendizado
let _learnSSE = null;
function startLearnSSE() {
  if (_learnSSE) return;
  try {
    _learnSSE = new EventSource('/api/learning/stream');
    _learnSSE.onmessage = e => { try { applyLearnStatus(JSON.parse(e.data)); } catch {} };
    _learnSSE.onerror = () => { _learnSSE.close(); _learnSSE = null; setTimeout(startLearnSSE, 8000); };
  } catch { _learnSSE = null; }
}

// #7 Lazy load: painéis só carregam na primeira abertura
const _panelLoaded = {};
function lazyLoad(id, fn) { if (!_panelLoaded[id]) { _panelLoaded[id] = true; fn(); } }

// #8 Load more messages
let _msgRenderLimit = 60;
const _MSG_PAGE = 40;

// #9 Request dedup por URL
const _inflight = new Map();
async function dedupFetch(url, opts={}) {
  const key = (opts.method||'GET')+'|'+url;
  if (_inflight.has(key)) { try { _inflight.get(key).abort(); } catch {} }
  const ctrl = new AbortController(); _inflight.set(key, ctrl);
  try { return await fetch(url, {...opts, signal: ctrl.signal}); }
  finally { if (_inflight.get(key)===ctrl) _inflight.delete(key); }
}

// Wrapper: adiciona #2 #3 #4 em respostas AI
function _enrichAiMessage(contentEl, fullText) {
  addInlineCopyButtons(contentEl);
  contentEl.querySelectorAll('.typing-dots').forEach(d=>d.remove());
  if (fullText && fullText.length > 20) contentEl.appendChild(buildReactionBar(fullText));
}

// ── #10 Múltiplas abas de chat ────────────────────────────────────────────────
const _MAX_TABS = 4;
let _tabs = [];       // [{id, session_id, label, snapshot}]
let _activeTabIdx = 0;

function _tabId() { return 'tab_' + Date.now().toString(36); }
function _newSessionId() { return crypto.randomUUID ? crypto.randomUUID() : _tabId(); }

function _snapshotMessages() {
  return document.getElementById('messages').innerHTML;
}
function _restoreMessages(html) {
  const box = document.getElementById('messages');
  box.innerHTML = html || '';
  box.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
}

function _renderTabs() {
  const bar = document.getElementById('tab-bar');
  // Remove itens antigos mantendo o botão +
  bar.querySelectorAll('.tab-item').forEach(t => t.remove());
  const addBtn = document.getElementById('tab-add');
  _tabs.forEach((tab, i) => {
    const item = document.createElement('div');
    item.className = 'tab-item' + (i === _activeTabIdx ? ' active' : '');
    item.innerHTML = `<span class="tab-label" title="${escHtml(tab.label)}">${escHtml(tab.label.slice(0,18))}</span>`;
    if (_tabs.length > 1) {
      const x = document.createElement('span');
      x.className = 'tab-close'; x.textContent = '×';
      x.onclick = (e) => { e.stopPropagation(); closeTab(i); };
      item.appendChild(x);
    }
    item.onclick = () => switchTab(i);
    bar.insertBefore(item, addBtn);
  });
  addBtn.style.display = _tabs.length >= _MAX_TABS ? 'none' : '';
}

function _saveTabs() {
  localStorage.setItem('apolo-tabs', JSON.stringify(
    _tabs.map((t, i) => ({...t, snapshot: i === _activeTabIdx ? _snapshotMessages() : t.snapshot}))
  ));
}

function addTab() {
  if (_tabs.length >= _MAX_TABS) return;
  // Salva snapshot da aba atual
  if (_tabs[_activeTabIdx]) _tabs[_activeTabIdx].snapshot = _snapshotMessages();
  const tab = { id: _tabId(), session_id: _newSessionId(), label: 'Chat ' + (_tabs.length + 1), snapshot: '' };
  _tabs.push(tab);
  _activeTabIdx = _tabs.length - 1;
  sessionId = tab.session_id;
  _restoreMessages('');
  showEmpty();
  _renderTabs();
  _saveTabs();
  document.getElementById('input').focus();
}

function switchTab(idx) {
  if (idx === _activeTabIdx) return;
  _tabs[_activeTabIdx].snapshot = _snapshotMessages();
  _tabs[_activeTabIdx].session_id = sessionId;
  _activeTabIdx = idx;
  sessionId = _tabs[idx].session_id;
  _restoreMessages(_tabs[idx].snapshot);
  if (!_tabs[idx].snapshot) showEmpty();
  _renderTabs();
  _saveTabs();
  scrollBottom();
}

function closeTab(idx) {
  if (_tabs.length <= 1) return;
  _tabs.splice(idx, 1);
  if (_activeTabIdx >= _tabs.length) _activeTabIdx = _tabs.length - 1;
  sessionId = _tabs[_activeTabIdx].session_id;
  _restoreMessages(_tabs[_activeTabIdx].snapshot);
  if (!_tabs[_activeTabIdx].snapshot) showEmpty();
  _renderTabs();
  _saveTabs();
}

function _updateTabLabel(label) {
  if (_tabs[_activeTabIdx]) {
    _tabs[_activeTabIdx].label = label.slice(0, 30) || 'Chat';
    _renderTabs();
    _saveTabs();
  }
}

function _initTabs() {
  // Restaura abas do localStorage ou cria a primeira aba
  try {
    const saved = JSON.parse(localStorage.getItem('apolo-tabs') || 'null');
    if (saved && saved.length) { _tabs = saved; _activeTabIdx = 0; }
  } catch {}
  if (!_tabs.length) _tabs = [{ id: _tabId(), session_id: sessionId, label: 'Chat 1', snapshot: '' }];
  else sessionId = _tabs[_activeTabIdx].session_id;
  _renderTabs();
  if (_tabs[_activeTabIdx].snapshot) _restoreMessages(_tabs[_activeTabIdx].snapshot);
}

// ── Modo Mãos Livres ─────────────────────────────────────────────────────────
// Máquina de estados: idle → listening → processing → thinking → speaking → listening
const HF = {
  state: 'idle',
  audioCtx: null, analyser: null, sourceNode: null, stream: null,
  recorder: null, chunks: [], vadTimer: null,
  waveRaf: null, waveCanvas: null, waveCtx2d: null,
  waveData: null, isRecording: false,
  // useServerTts: usa o TTS do servidor (Piper local OU edge nuvem) via /api/tts;
  // false = cai para a voz do navegador. ttsEngine guarda qual engine respondeu.
  useServerTts: false, ttsEngine: 'browser', hfVoice: 'feminino',
  VOICES: { feminino: 'pt-BR-FranciscaNeural', masculino: 'pt-BR-AntonioNeural' },
  ENERGY_THRESHOLD: 18,   // energia mínima para considerar fala (0–255)
  SILENCE_MS: 1600,        // ms de silêncio para encerrar gravação
  MIN_AUDIO_MS: 400,       // áudio mínimo para enviar (evita clips vazios)
  _recStart: 0,
};

function _hfSetState(s) {
  HF.state = s;
  document.getElementById('hf-overlay').dataset.state = s;
  const labels = {
    idle:'',listening:'Ouvindo...',processing:'Transcrevendo...',
    thinking:'Pensando...', speaking:'Falando...'
  };
  const subs = {
    idle:'',listening:'Fale normalmente — silêncio por 1,6s envia automaticamente',
    processing:'Aguarde...', thinking:'Gerando resposta...',
    speaking:'A.P.O.L.O. está respondendo'
  };
  document.getElementById('hf-status').textContent = labels[s] ?? s;
  document.getElementById('hf-status-sub').textContent = subs[s] ?? '';
}

function _hfEnergy() {
  if (!HF.analyser || !HF.waveData) return 0;
  HF.analyser.getByteFrequencyData(HF.waveData);
  return HF.waveData.reduce((a,b)=>a+b,0) / HF.waveData.length;
}

function _hfDrawWave() {
  if (HF.state === 'idle') return;
  const canvas = HF.waveCanvas, ctx = HF.waveCtx2d;
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0,0,W,H);
  if (HF.analyser && HF.waveData) {
    HF.analyser.getByteFrequencyData(HF.waveData);
    const bars = 48, bw = W/bars;
    for (let i=0;i<bars;i++) {
      const val = HF.waveData[Math.floor(i*HF.waveData.length/bars)];
      const h = (val/255) * H * 0.9;
      const alpha = HF.state==='listening' ? 0.3+val/255*0.7 : 0.15+val/255*0.3;
      const color = HF.state==='speaking' ? `rgba(251,191,36,${alpha})`
                  : HF.state==='listening' ? `rgba(74,222,128,${alpha})`
                  : `rgba(148,163,184,${alpha})`;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.roundRect(i*bw+1, H-h, bw-2, h, 2);
      ctx.fill();
    }
    const energy = HF.waveData.reduce((a,b)=>a+b,0)/HF.waveData.length;
    document.getElementById('hf-meter-fill').style.width =
      Math.min(100, energy/HF.ENERGY_THRESHOLD*50) + '%';
  }
  HF.waveRaf = requestAnimationFrame(_hfDrawWave);
}

function _hfAddBubble(role, text) {
  const el = document.createElement('div');
  el.className = 'hf-bubble ' + role;
  el.textContent = (role==='user' ? '🎙️ ' : '☀️ ') + text.slice(0,300);
  const box = document.getElementById('hf-transcript');
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

async function _hfStartListening() {
  if (HF.state === 'idle') return;
  _hfSetState('listening');
  HF.chunks = []; HF.isRecording = false;
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus' : 'audio/webm';
  HF.recorder = new MediaRecorder(HF.stream, {mimeType});
  HF.recorder.ondataavailable = e => { if (e.data.size > 0) HF.chunks.push(e.data); };
  HF.recorder.start(100); // timeslice = pega dados a cada 100ms

  // VAD loop
  function vadTick() {
    if (HF.state !== 'listening') return;
    const e = _hfEnergy();
    if (e > HF.ENERGY_THRESHOLD) {
      if (!HF.isRecording) { HF.isRecording = true; HF._recStart = Date.now(); }
      clearTimeout(HF.vadTimer); HF.vadTimer = null;
    } else if (HF.isRecording && !HF.vadTimer) {
      HF.vadTimer = setTimeout(() => _hfSendAudio(), HF.SILENCE_MS);
    }
    requestAnimationFrame(vadTick);
  }
  requestAnimationFrame(vadTick);
}

async function _hfSendAudio() {
  if (HF.state !== 'listening') return;
  const duration = Date.now() - HF._recStart;
  HF.recorder.stop();
  clearTimeout(HF.vadTimer); HF.vadTimer = null;

  if (!HF.isRecording || duration < HF.MIN_AUDIO_MS) {
    // Muito curto — volta a ouvir
    setTimeout(() => _hfStartListening(), 300);
    return;
  }

  _hfSetState('processing');
  await new Promise(r => HF.recorder.onstop = r);
  const blob = new Blob(HF.chunks, {type:'audio/webm'});

  let transcript = '';
  // Tenta Whisper local; fallback para Web Speech API (que não funciona no loop assim,
  // então apenas avisa se o servidor STT não está disponível)
  try {
    const res = await fetch('/api/stt', {method:'POST', body:blob});
    const d = await res.json();
    transcript = d.ok ? d.text : '';
    if (!d.ok) {
      _hfSetState('listening');
      setTimeout(() => _hfStartListening(), 500);
      return;
    }
  } catch {
    _hfSetState('listening');
    setTimeout(() => _hfStartListening(), 500);
    return;
  }

  if (!transcript.trim()) {
    _hfSetState('listening');
    setTimeout(() => _hfStartListening(), 300);
    return;
  }

  _hfAddBubble('user', transcript);
  _hfSetState('thinking');
  await _hfChat(transcript);
}

async function _hfChat(text) {
  // Usa o mesmo streamChatResponse mas captura o texto completo para TTS
  let full = '';
  try {
    const resp = await fetch('/api/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message:text, session_id:sessionId}),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder(); let buf='';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      const parts = buf.split('\n\n'); buf = parts.pop();
      for (const p of parts) {
        if (!p.startsWith('data: ')) continue;
        const d = JSON.parse(p.slice(6));
        if (d.type==='token') full += d.content;
        if (d.type==='done') break;
      }
    }
  } catch(e) {
    _hfSetState('listening');
    setTimeout(() => _hfStartListening(), 500);
    return;
  }

  if (!full.trim()) { _hfSetState('listening'); setTimeout(() => _hfStartListening(), 300); return; }

  // Mostra no chat principal também
  addUserMessage(text);
  const wrap = createAiMessage(); wrap.querySelector('.content').innerHTML = renderMd(full);
  wrap.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
  scrollBottom();

  // Texto para TTS: remove markdown
  const ttsText = full
    .replace(/```[\s\S]*?```/g,'. (código) .')
    .replace(/`([^`]+)`/g,'$1')
    .replace(/[#*_~>]/g,'')
    .replace(/\[([^\]]+)\]\([^)]+\)/g,'$1')
    .replace(/\n{2,}/g,'. ')
    .trim().slice(0,2000);

  _hfAddBubble('ai', ttsText.slice(0,200));
  _hfSetState('speaking');

  await _hfSpeak(ttsText);

  if (HF.state !== 'idle') _hfStartListening();
}

async function _hfSpeak(text) {
  if (HF.useServerTts) {
    try {
      // Envia o RÓTULO da voz (feminino/masculino) — a fachada de TTS mapeia para
      // o modelo certo em qualquer engine (Piper local ou edge nuvem).
      const resp = await fetch(`/api/tts?${new URLSearchParams({text:text.slice(0,2000),voice:HF.hfVoice})}`);
      if (!resp.ok) throw new Error('TTS do servidor falhou');
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.volume = 1.0;
      await audio.play();
      await new Promise((res, rej) => {
        audio.onended = res;
        audio.onerror = rej;
        // Se sair do modo voz enquanto fala, para
        const check = setInterval(() => { if (HF.state==='idle'){audio.pause();URL.revokeObjectURL(url);clearInterval(check);res();} }, 200);
      });
      URL.revokeObjectURL(url);
      return;
    } catch { /* fallback */ }
  }
  // Fallback: browser speechSynthesis
  return new Promise(res => {
    if (!('speechSynthesis' in window)) { res(); return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.slice(0,3000));
    u.lang='pt-BR'; u.rate=1.05;
    if (ptVoice) u.voice=ptVoice;
    u.onend = () => res();
    u.onerror = () => res();
    speechSynthesis.speak(u);
  });
}

async function startHandsFree() {
  if (HF.state !== 'idle') return;
  // Verifica se Whisper está disponível
  try {
    const h = await fetch('/api/health').then(r=>r.json());
    if (!h.stt) {
      alert('O modo Mãos Livres requer o Whisper STT local.\nInstale: pip install faster-whisper\nReinicie o servidor e tente de novo.');
      return;
    }
    // Usa o TTS do servidor para QUALQUER engine != browser (Piper local ou edge
    // nuvem). Antes só reconhecia 'edge-tts' e ignorava o Piper (voz soberana).
    HF.ttsEngine = h.tts_engine || 'browser';
    HF.useServerTts = HF.ttsEngine !== 'browser';
    document.getElementById('hf-voice-btn').textContent =
      '🔊 ' + (HF.useServerTts ? HF.hfVoice : 'browser');
    // STT ainda aquecendo? avisa que a 1ª fala pode demorar (sem bloquear).
    if (h.stt && h.stt_ready === false)
      _hfAddBubble('ai', 'preparando a voz (carregando o modelo)...');
  } catch { return; }

  // Inicializa AudioContext + MediaStream
  try {
    HF.stream = await navigator.mediaDevices.getUserMedia({audio:true, video:false});
  } catch { alert('Acesso ao microfone negado.'); return; }

  HF.audioCtx = new AudioContext();
  HF.analyser = HF.audioCtx.createAnalyser();
  HF.analyser.fftSize = 256;
  HF.waveData = new Uint8Array(HF.analyser.frequencyBinCount);
  HF.sourceNode = HF.audioCtx.createMediaStreamSource(HF.stream);
  HF.sourceNode.connect(HF.analyser);

  // Canvas
  HF.waveCanvas = document.getElementById('hf-wave');
  HF.waveCtx2d = HF.waveCanvas.getContext('2d');
  document.getElementById('hf-transcript').innerHTML = '';

  document.getElementById('hf-overlay').classList.add('active');
  _hfSetState('listening');
  _hfDrawWave();
  _hfStartListening();
}

function stopHandsFree() {
  _hfSetState('idle');
  cancelAnimationFrame(HF.waveRaf);
  clearTimeout(HF.vadTimer);
  speechSynthesis.cancel();
  try { HF.recorder?.stop(); } catch {}
  try { HF.stream?.getTracks().forEach(t=>t.stop()); } catch {}
  try { HF.audioCtx?.close(); } catch {}
  HF.audioCtx=null; HF.analyser=null; HF.sourceNode=null;
  HF.stream=null; HF.recorder=null; HF.chunks=[];
  document.getElementById('hf-overlay').classList.remove('active');
  document.getElementById('hf-meter-fill').style.width='0%';
}

function cycleHfVoice() {
  const voices = Object.keys(HF.VOICES);
  const idx = voices.indexOf(HF.hfVoice);
  HF.hfVoice = voices[(idx+1) % voices.length];
  document.getElementById('hf-voice-btn').textContent =
    '🔊 ' + (HF.useServerTts ? HF.hfVoice : 'browser');
}

// ── PWA: Service Worker ──────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then(reg => console.log('[SW] registrado, scope:', reg.scope))
      .catch(err => console.warn('[SW] falha:', err));
  });
}

// ── PWA: Prompt de instalação (Android/Chrome) ────────────────────────────────
let _deferredInstall = null;
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  _deferredInstall = e;
  document.getElementById('pwa-install-btn').classList.add('show');
});
document.getElementById('pwa-install-btn').addEventListener('click', async () => {
  if (!_deferredInstall) return;
  _deferredInstall.prompt();
  const { outcome } = await _deferredInstall.userChoice;
  if (outcome === 'accepted') {
    document.getElementById('pwa-install-btn').classList.remove('show');
    _deferredInstall = null;
  }
});
window.addEventListener('appinstalled', () => {
  document.getElementById('pwa-install-btn').classList.remove('show');
  _deferredInstall = null;
});

// ── PWA: Detecção de offline ──────────────────────────────────────────────────
function _updateOnline() {
  document.getElementById('offline-bar').classList.toggle('show', !navigator.onLine);
}
window.addEventListener('online', _updateOnline);
window.addEventListener('offline', _updateOnline);
_updateOnline();

// ── Mobile: Sidebar hambúrguer ────────────────────────────────────────────────
function _isMobile() { return window.innerWidth <= 600; }

function toggleMobileSidebar() {
  document.getElementById('sidebar').classList.toggle('mobile-open');
  document.getElementById('sidebar-backdrop').classList.toggle('show');
}
function closeMobileSidebar() {
  document.getElementById('sidebar').classList.remove('mobile-open');
  document.getElementById('sidebar-backdrop').classList.remove('show');
}

// Fechar sidebar ao navegar para sessão no mobile
const _origResume = typeof resumeSession === 'function' ? resumeSession : null;
if (_origResume) {
  window.resumeSession = function(id) { _origResume(id); if (_isMobile()) closeMobileSidebar(); };
}

function _applyMobileUI() {
  const mobile = _isMobile();
  document.getElementById('mobile-menu-btn').style.display = mobile ? 'flex' : 'none';
  if (!mobile) {
    document.getElementById('sidebar').classList.remove('mobile-open');
    document.getElementById('sidebar-backdrop').classList.remove('show');
  }
}
window.addEventListener('resize', _applyMobileUI);
_applyMobileUI();
