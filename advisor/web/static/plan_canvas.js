/**
 * plan_canvas.js — Plan Canvas side panel
 *
 * Persistent split-view canvas shown alongside the chat when a plan draft is
 * active. Shows command cards (ordered), narrative text per card, drag-to-
 * reorder, add/remove commands, and syncs changes back to the draft spec.
 *
 * Public API (global PlanCanvas object):
 *   PlanCanvas.open(draftId)   — show panel and load draft
 *   PlanCanvas.close()         — hide panel
 *   PlanCanvas.refresh(draftId) — reload draft from server and re-render
 *   PlanCanvas.addStep()       — prompt to add a new command card
 */
const PlanCanvas = (() => {

  // ── State ──────────────────────────────────────────────────────────────────

  let _draftId    = null;
  let _spec       = null;   // full draft spec from server
  let _dragSrcIdx = null;
  let _mode       = localStorage.getItem('ea_canvas_mode') || 'basic';  // 'basic' | 'advanced'

  // ── Public entry points ────────────────────────────────────────────────────

  async function open(draftId) {
    if (!draftId) return;
    _draftId = draftId;

    const panel  = document.getElementById('plan-canvas-panel');
    const handle = document.getElementById('resize-chat-canvas');
    panel.classList.remove('hidden');
    panel.classList.add('flex');
    handle.classList.remove('hidden');
    if (window._applyCanvasWidth) window._applyCanvasWidth();

    // Sync mode button label to persisted state
    const modeBtn = document.getElementById('pcanvas-mode-btn');
    if (modeBtn) modeBtn.textContent = _mode === 'basic' ? 'Basic' : 'Advanced';

    await refresh(draftId);
  }

  function close() {
    _draftId = null;
    _spec    = null;
    const panel  = document.getElementById('plan-canvas-panel');
    const handle = document.getElementById('resize-chat-canvas');
    panel.classList.add('hidden');
    panel.classList.remove('flex');
    handle.classList.add('hidden');
  }

  async function refresh(draftId) {
    if (!draftId) return;
    try {
      const r = await fetch(`/api/drafts/${encodeURIComponent(draftId)}`);
      if (!r.ok) return;
      _spec = await r.json();
    } catch { return; }
    _render();
  }

  async function addStep() {
    const action = prompt('Command name (e.g. "Create Project", "Create Glossary Term"):');
    if (!action || !action.trim()) return;
    if (!_spec) return;
    const cmd = {
      action:       action.trim(),
      display_name: '',
      description:  '',
      rationale:    '',
      narrative:    '',
      pre_filled:   {},
      placeholders: {},
    };
    _spec.commands_identified.push(cmd);
    await _syncToServer();
    _render();
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function _render() {
    if (!_spec) return;
    const container = document.getElementById('pcanvas-cards');
    const titleEl   = document.getElementById('pcanvas-title');
    if (!container || !titleEl) return;

    titleEl.textContent = _spec.title || '';
    // Show Execute button once the plan document has been generated
    const docId = _spec.doc_id;
    titleEl.dataset.docId = docId || '';
    const execBtn = document.getElementById('pcanvas-execute-btn');
    if (execBtn) execBtn.classList.toggle('hidden', !docId);
    container.innerHTML = '';

    const commands = _spec.commands_identified || [];
    commands.forEach((cmd, idx) => {
      container.appendChild(_buildCard(cmd, idx, commands.length));
    });

    if (!commands.length) {
      container.innerHTML =
        '<p class="text-xs text-slate-600 text-center py-6">No steps yet — describe what you want in the chat.</p>';
    }
  }

  function _buildCard(cmd, idx, total) {
    const answers    = _spec.answers || {};
    const answersKey = cmd._answers_key || cmd.action;
    const filled     = answers[answersKey] || answers[cmd.action] || cmd.pre_filled || {};
    const dn         = filled['Display Name'] || cmd.display_name || '';

    // Known params (pre_filled + answers, excluding Display Name)
    const knownParams = { ...cmd.pre_filled, ...filled };
    delete knownParams['Display Name'];
    const paramChips = Object.entries(knownParams)
      .filter(([, v]) => v)
      .map(([k, v]) => `<span class="text-slate-500 text-xs">✓ ${_esc(k)}: <em>${_esc(v)}</em></span>`)
      .join('');

    // Status: amber if display_name missing, green otherwise
    const statusColor = dn ? 'bg-emerald-500' : 'bg-amber-400';
    const statusTitle = dn ? 'Name set' : 'Display Name missing';

    // Narrative text
    const narrative = cmd.narrative || '';

    const card = document.createElement('div');
    card.className = 'pcanvas-card bg-slate-900 rounded-lg border border-slate-700/60 overflow-hidden select-none';
    card.dataset.idx = idx;
    card.draggable = true;

    card.innerHTML = `
      <!-- Header row -->
      <div class="card-header flex items-center gap-1.5 px-2.5 py-2 cursor-grab active:cursor-grabbing">
        <span class="drag-grip text-slate-600 text-base leading-none shrink-0 select-none">≡</span>
        <span class="text-slate-600 text-xs w-5 shrink-0 text-right">${idx + 1}.</span>
        <span class="text-violet-300 text-xs font-semibold flex-1 truncate">${_esc(cmd.action)}</span>
        <span class="w-2 h-2 rounded-full shrink-0 ${statusColor}" title="${statusTitle}"></span>
        <button class="expand-btn text-slate-500 hover:text-slate-200 text-xs px-1 transition-colors" title="Expand fields">▾</button>
        <button class="remove-btn text-slate-700 hover:text-red-400 text-xs px-1 transition-colors" title="Remove this step">✕</button>
      </div>

      <!-- Display name + known params (always visible) -->
      <div class="px-2.5 pb-1.5 flex flex-col gap-0.5">
        <span class="display-name text-slate-200 text-sm font-medium">${_esc(dn) || '<span class="text-slate-600 italic">name TBD</span>'}</span>
        ${paramChips ? `<div class="flex flex-wrap gap-x-3 gap-y-0.5">${paramChips}</div>` : ''}
      </div>

      <!-- Narrative textarea -->
      <div class="narrative-wrap px-2.5 pb-2">
        <textarea class="narrative-input w-full bg-slate-800/60 text-slate-400 text-xs rounded p-1.5
                         resize-none border border-slate-700/50 focus:outline-none focus:border-violet-500/40
                         transition-colors placeholder-slate-600"
          rows="2"
          placeholder="Rationale, instructions, or notes…"
          data-idx="${idx}">${_esc(narrative)}</textarea>
      </div>

      <!-- Expanded fields (hidden by default, max-height + scroll) -->
      <div class="fields-section hidden px-2.5 pb-2.5 flex flex-col gap-1.5 max-h-64 overflow-y-auto"></div>
    `;

    // ── Drag-and-drop ───────────────────────────────────────────────────────
    card.addEventListener('dragstart', e => {
      _dragSrcIdx = idx;
      card.classList.add('drag-ghost');
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('drag-ghost');
      document.querySelectorAll('.pcanvas-card').forEach(c => c.classList.remove('dragging-over'));
    });
    card.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      document.querySelectorAll('.pcanvas-card').forEach(c => c.classList.remove('dragging-over'));
      if (_dragSrcIdx !== idx) card.classList.add('dragging-over');
    });
    card.addEventListener('dragleave', () => card.classList.remove('dragging-over'));
    card.addEventListener('drop', async e => {
      e.preventDefault();
      card.classList.remove('dragging-over');
      if (_dragSrcIdx === null || _dragSrcIdx === idx) return;
      await _reorderCommands(_dragSrcIdx, idx);
      _dragSrcIdx = null;
    });

    // ── Remove ──────────────────────────────────────────────────────────────
    card.querySelector('.remove-btn').addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm(`Remove step "${cmd.action}"?`)) return;
      await _removeCommand(idx);
    });

    // ── Expand toggle ───────────────────────────────────────────────────────
    card.querySelector('.expand-btn').addEventListener('click', e => {
      e.stopPropagation();
      const fieldsSection = card.querySelector('.fields-section');
      const btn = card.querySelector('.expand-btn');
      const isOpen = !fieldsSection.classList.contains('hidden');
      fieldsSection.classList.toggle('hidden', isOpen);
      btn.textContent = isOpen ? '▾' : '▴';
      if (!isOpen) _loadFieldsIntoCard(card, cmd, idx);
    });

    // ── Narrative autosave ──────────────────────────────────────────────────
    let narrativeTimer;
    card.querySelector('.narrative-input').addEventListener('input', e => {
      clearTimeout(narrativeTimer);
      narrativeTimer = setTimeout(async () => {
        if (_spec && _spec.commands_identified[idx]) {
          _spec.commands_identified[idx].narrative = e.target.value;
          await _syncToServer();
        }
      }, 800);
    });

    return card;
  }

  // ── Field expansion ────────────────────────────────────────────────────────

  async function _loadFieldsIntoCard(card, cmd, idx) {
    const section = card.querySelector('.fields-section');
    section.innerHTML = '<p class="text-xs text-slate-600">Loading fields…</p>';

    let fields = [];
    try {
      const r = await fetch(`/api/templates/${encodeURIComponent(cmd.action)}/fields?level=${_mode}`);
      if (r.ok) {
        const data = await r.json();
        fields = data.fields || [];
      }
    } catch { /* no fields available */ }

    const answers    = _spec.answers || {};
    const answersKey = cmd._answers_key || cmd.action;
    const filled     = answers[answersKey] || answers[cmd.action] || {};

    section.innerHTML = '';
    if (!fields.length) {
      section.innerHTML = '<p class="text-xs text-slate-600">No template fields found.</p>';
      return;
    }

    fields.forEach(f => {
      const val = filled[f.name] || cmd.pre_filled?.[f.name] || '';
      const row = document.createElement('div');
      row.className = 'flex flex-col gap-0.5';
      row.innerHTML = `
        <label class="text-xs text-slate-500 flex items-center gap-1">
          ${_esc(f.name)}
          ${f.required ? '<span class="text-amber-400 text-xs">*</span>' : ''}
        </label>
        <input type="text" value="${_esc(val)}"
          class="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200
                 focus:outline-none focus:border-violet-500/60 transition-colors"
          placeholder="${_esc(f.description || '')}"
          data-field="${_esc(f.name)}" data-idx="${idx}" />
      `;

      let fieldTimer;
      row.querySelector('input').addEventListener('input', e => {
        clearTimeout(fieldTimer);
        fieldTimer = setTimeout(async () => {
          const key = cmd._answers_key || cmd.action;
          if (!_spec.answers[key]) _spec.answers[key] = {};
          _spec.answers[key][f.name] = e.target.value;
          if (f.name === 'Display Name') {
            _spec.commands_identified[idx].display_name = e.target.value;
          }
          await _syncToServer();
          // Refresh display name / params in card header without full re-render
          _updateCardSummary(card, idx);
        }, 600);
      });

      section.appendChild(row);
    });
  }

  function _updateCardSummary(card, idx) {
    if (!_spec) return;
    const cmd        = _spec.commands_identified[idx];
    const answers    = _spec.answers || {};
    const answersKey = cmd._answers_key || cmd.action;
    const filled     = answers[answersKey] || answers[cmd.action] || cmd.pre_filled || {};
    const dn         = filled['Display Name'] || cmd.display_name || '';
    const dnEl = card.querySelector('.display-name');
    if (dnEl) dnEl.innerHTML = dn ? _esc(dn) : '<span class="text-slate-600 italic">name TBD</span>';
    const dot = card.querySelector('.w-2.h-2.rounded-full');
    if (dot) {
      dot.className = `w-2 h-2 rounded-full shrink-0 ${dn ? 'bg-emerald-500' : 'bg-amber-400'}`;
    }
  }

  // ── Command mutations ──────────────────────────────────────────────────────

  async function _removeCommand(idx) {
    if (!_spec) return;
    const removed = _spec.commands_identified.splice(idx, 1)[0];
    // Also remove answers for this command
    if (removed) {
      const key = removed._answers_key || removed.action;
      delete _spec.answers[key];
    }
    await _syncToServer();
    _render();
  }

  async function _reorderCommands(fromIdx, toIdx) {
    if (!_spec) return;
    const cmds = _spec.commands_identified;
    const [moved] = cmds.splice(fromIdx, 1);
    cmds.splice(toIdx, 0, moved);
    await _syncToServer();
    _render();
  }

  // ── Server sync ────────────────────────────────────────────────────────────

  async function _syncToServer() {
    if (!_draftId || !_spec) return;
    try {
      await fetch(`/api/drafts/${encodeURIComponent(_draftId)}/commands`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          commands: _spec.commands_identified,
          answers:  _spec.answers,
        }),
      });
    } catch (e) {
      console.warn('PlanCanvas: sync failed', e);
    }
  }

  // ── Utilities ──────────────────────────────────────────────────────────────

  function _esc(s) {
    if (!s) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Mode toggle ────────────────────────────────────────────────────────────

  function toggleMode() {
    _mode = _mode === 'basic' ? 'advanced' : 'basic';
    localStorage.setItem('ea_canvas_mode', _mode);
    // Update button label
    const btn = document.getElementById('pcanvas-mode-btn');
    if (btn) btn.textContent = _mode === 'basic' ? 'Basic' : 'Advanced';
    // Reload any currently open field sections
    document.querySelectorAll('.fields-section:not(.hidden)').forEach(section => {
      const card = section.closest('.pcanvas-card');
      if (!card) return;
      const idx = parseInt(card.dataset.idx);
      if (!isNaN(idx) && _spec?.commands_identified[idx]) {
        _loadFieldsIntoCard(card, _spec.commands_identified[idx], idx);
      }
    });
  }

  // ── Public interface ───────────────────────────────────────────────────────

  return { open, close, refresh, addStep, toggleMode };

})();
