// ── Plan Editor ────────────────────────────────────────────────────────────────
// Inline editor for Literate Governance plan documents.
// Parses the plan markdown into a structured form (narrative textarea + per-command
// field cards with inter-command notes), synthesises back to markdown on save,
// and exposes Validate / Execute.

'use strict';

// ── State ──────────────────────────────────────────────────────────────────────
let _ped = {
  doc_id:        null,
  isInbox:       true,
  mode:          'basic',      // 'basic' | 'advanced'
  narrative:     '',           // everything before ## Command Sequence
  commands:      [],           // [{stepNum, action, rationale, fields, postNotes}]
  outcome:       '',           // ## Outcome section (read-only)
  templateCache: {},           // "action:level" → [{name,required,type,...}]
  dirty:         false,
};

// ── Public entry points ────────────────────────────────────────────────────────

async function openPlanEditor(doc_id) {
  let data;
  try {
    const r = await fetch(`/api/plans/${encodeURIComponent(doc_id)}`);
    if (!r.ok) { alert(`Could not load plan ${doc_id}`); return; }
    data = await r.json();
  } catch (e) { alert(`Error loading plan: ${e.message}`); return; }

  _ped.doc_id  = doc_id;
  _ped.isInbox = (data.folder === 'inbox');
  _ped.dirty   = false;

  const parsed    = _parsePlanMarkdown(data.content);
  _ped.narrative  = parsed.narrative;
  _ped.commands   = parsed.commands;
  _ped.outcome    = parsed.outcome;

  _renderEditor();
  document.getElementById('plan-editor-overlay').classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  // Load template field metadata in background — enriches required/optional and re-renders
  _loadAllTemplateFields();
}

function closePlanEditor() {
  if (_ped.dirty && !confirm('You have unsaved changes. Close anyway?')) return;
  document.getElementById('plan-editor-overlay').classList.add('hidden');
  document.body.style.overflow = '';
  _ped.doc_id = null;
}

// ── Markdown parsing ───────────────────────────────────────────────────────────

function _parsePlanMarkdown(md) {
  const cmdSeqRe    = /^##\s+Command Sequence\s*$/m;
  const cmdSeqMatch = cmdSeqRe.exec(md);

  let narrative = md;
  let cmdBody   = '';
  let outcome   = '';

  if (cmdSeqMatch) {
    narrative = md.slice(0, cmdSeqMatch.index).trimEnd();
    let rest  = md.slice(cmdSeqMatch.index + cmdSeqMatch[0].length).trimStart();

    const outcomeRe = /^##\s+Outcome\s*$/m;
    const outMatch  = outcomeRe.exec(rest);
    if (outMatch) {
      outcome = rest.slice(outMatch.index).trimStart();
      rest    = rest.slice(0, outMatch.index).trimEnd();
    }
    cmdBody = rest;
  }

  const commands = [];
  const blocks   = cmdBody.split(/(?=^<!--\s*Step\s+\d+)/m).filter(b => b.trim());

  for (const block of blocks) {
    const commentRe = /^<!--\s*Step\s+(\d+):\s*([\s\S]*?)-->/;
    const cm        = commentRe.exec(block);
    if (!cm) continue;

    const stepNum     = parseInt(cm[1], 10);
    const cLines      = cm[2].trim().split('\n').map(l => l.trim().replace(/^\s+/, '')).filter(Boolean);
    const action      = cLines[0] || '';
    const rationale   = cLines.slice(1).join('\n').trim();

    // Parse ### FieldName / value sections
    const fields = [];
    const afterComment = block.slice(cm.index + cm[0].length);
    const afterHeading = afterComment.replace(/^\s*##[^\n]*\n/, '');

    // Capture the section before any postNotes (text after the closing ---)
    // Each command block ends with --- (horizontal rule). Anything after is postNotes.
    const hrIdx    = afterHeading.search(/\n---\s*(\n|$)/);
    const fieldsBody = hrIdx !== -1 ? afterHeading.slice(0, hrIdx) : afterHeading;
    const postNotes  = hrIdx !== -1 ? afterHeading.slice(hrIdx).replace(/^\n---\s*\n?/, '').trim() : '';

    const fieldParts = fieldsBody.split(/(?=^###\s)/m);
    for (const fp of fieldParts) {
      const fm = /^###\s+([^\n]+)\n([\s\S]*?)$/.exec(fp.trim());
      if (!fm) continue;
      const name  = fm[1].trim();
      const raw   = fm[2].replace(/\n?---\s*$/, '').trim();
      const value = /<!--\s*TODO/i.test(raw) ? '' : raw;
      fields.push({ name, value, required: false, type: 'Simple', validValues: [] });
    }

    commands.push({ stepNum, action, rationale, fields, postNotes });
  }

  return { narrative, commands, outcome };
}

// ── Markdown synthesis ─────────────────────────────────────────────────────────

function _synthesizePlanMarkdown() {
  const narrativeEl = document.getElementById('ped-narrative');
  const narrative   = narrativeEl ? narrativeEl.value : _ped.narrative;

  let md = narrative + '\n\n---\n\n## Command Sequence\n\n';

  for (const cmd of _ped.commands) {
    const commentLines = [cmd.action];
    if (cmd.rationale) commentLines.push('     ' + cmd.rationale);
    md += `<!-- Step ${cmd.stepNum}: ${commentLines.join('\n')} -->\n`;
    md += `## ${cmd.action}\n\n`;

    for (const f of cmd.fields) {
      // In basic mode, skip empty optional fields to keep the document clean
      if (_ped.mode === 'basic' && !f.required && !f.value.trim()) continue;
      const val = f.value.trim() || '<!-- TODO: fill in -->';
      md += `### ${f.name}\n${val}\n\n`;
    }
    md += '---\n\n';

    // Inter-command narrative (postNotes) — free text between commands
    const notes = _getPostNotes(cmd);
    if (notes.trim()) md += notes.trim() + '\n\n';
  }

  if (_ped.outcome) md += '\n' + _ped.outcome;
  return md;
}

// Read postNotes from DOM (textarea) if rendered, else from state
function _getPostNotes(cmd) {
  const ta = document.querySelector(`[data-notes-for="${cmd.stepNum}"]`);
  return ta ? ta.value : (cmd.postNotes || '');
}

// ── Template field loading ─────────────────────────────────────────────────────

async function _loadAllTemplateFields() {
  const actions = [...new Set(_ped.commands.map(c => c.action))];
  await Promise.all(actions.map(a => _fetchTemplateFields(a, _ped.mode)));
  _enrichFieldMetadata();
  _renderCommandCards();
}

async function _fetchTemplateFields(action, level = 'basic') {
  const cacheKey = `${action}:${level}`;
  if (cacheKey in _ped.templateCache) return _ped.templateCache[cacheKey];

  try {
    const url = `/api/templates/${encodeURIComponent(action)}/fields?level=${encodeURIComponent(level)}`;
    const r   = await fetch(url);
    if (r.ok) {
      const data = await r.json();
      _ped.templateCache[cacheKey] = data.fields || [];
    } else {
      _ped.templateCache[cacheKey] = [];
    }
  } catch {
    _ped.templateCache[cacheKey] = [];
  }
  return _ped.templateCache[cacheKey];
}

function _enrichFieldMetadata() {
  for (const cmd of _ped.commands) {
    const cacheKey = `${cmd.action}:${_ped.mode}`;
    const tmpl     = _ped.templateCache[cacheKey] || _ped.templateCache[`${cmd.action}:basic`] || [];
    const byName   = Object.fromEntries(tmpl.map(f => [f.name, f]));

    // Update type/required metadata on existing fields
    for (const f of cmd.fields) {
      const td = byName[f.name];
      if (td) { f.required = td.required; f.type = td.type; f.validValues = td.valid_values || []; f.description = td.description || ''; }
    }

    // In advanced mode: add ALL template fields not already present
    // In basic mode: add only required fields not already present
    const presentNames = new Set(cmd.fields.map(f => f.name));
    for (const td of tmpl) {
      const shouldAdd = td.required || _ped.mode === 'advanced';
      if (shouldAdd && !presentNames.has(td.name)) {
        const field = { name: td.name, value: td.default_value || '', required: td.required, type: td.type, validValues: td.valid_values || [], description: td.description || '' };
        td.required ? cmd.fields.unshift(field) : cmd.fields.push(field);
        presentNames.add(td.name);
      }
    }
  }
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function _renderEditor() {
  const overlay = document.getElementById('plan-editor-overlay');

  // Title
  const titleMatch = _ped.narrative.match(/^#\s+(.+)/m);
  const title = titleMatch ? titleMatch[1].replace('Data Management Plan: ', '') : (_ped.doc_id || '');
  overlay.querySelector('#ped-title').textContent = title;

  // Wire toolbar buttons
  overlay.querySelector('#ped-save-btn').onclick     = _savePlanEdits;
  overlay.querySelector('#ped-validate-btn').onclick = _validatePlanDoc;
  overlay.querySelector('#ped-execute-btn').onclick  = _executePlanDoc;

  const modeBtn = overlay.querySelector('#ped-mode-btn');
  if (modeBtn) {
    modeBtn.textContent = _ped.mode === 'basic' ? 'Basic' : 'Advanced';
    modeBtn.onclick     = _toggleMode;
  }

  // Disable editing for outbox plans
  const editable = _ped.isInbox;
  overlay.querySelector('#ped-save-btn').disabled     = !editable;
  overlay.querySelector('#ped-validate-btn').disabled = !editable;
  overlay.querySelector('#ped-execute-btn').disabled  = !editable;
  overlay.querySelector('#ped-execute-btn').textContent = editable ? '▶ Execute' : '(Executed)';

  // Narrative textarea
  const narrativeEl = overlay.querySelector('#ped-narrative');
  narrativeEl.value    = _ped.narrative;
  narrativeEl.readOnly = !editable;
  narrativeEl.oninput  = () => { _ped.dirty = true; _updateStatusBar(); };

  // Outcome section (read-only)
  const outcomeEl = overlay.querySelector('#ped-outcome');
  if (_ped.outcome) {
    outcomeEl.classList.remove('hidden');
    outcomeEl.querySelector('.ped-outcome-body').innerHTML =
      typeof marked !== 'undefined' ? marked.parse(_ped.outcome) : _ped.outcome.replace(/\n/g, '<br>');
  } else {
    outcomeEl.classList.add('hidden');
  }

  _renderCommandCards();
  _updateStatusBar();
}

function _renderCommandCards() {
  const container = document.getElementById('ped-commands');
  container.innerHTML = '';
  _ped.commands.forEach((cmd, idx) => container.appendChild(_buildCommandCard(cmd, idx)));
}

function _buildCommandCard(cmd, idx) {
  const card = document.createElement('div');
  card.className = 'ped-cmd-card bg-slate-800 rounded-lg border border-slate-700 overflow-hidden';
  card.dataset.idx = idx;

  // ── Card header ──────────────────────────────────────────────────────
  const hdr = document.createElement('div');
  hdr.className = 'flex items-center gap-2 px-4 py-2 cursor-pointer select-none border-b border-slate-700';
  hdr.style.background = '#1e293b';
  hdr.innerHTML =
    `<span class="text-xs font-semibold text-violet-400 shrink-0">Step ${cmd.stepNum}</span>` +
    `<span class="text-sm font-semibold text-slate-100 flex-1">${_esc(cmd.action)}</span>` +
    `<span class="ped-cmd-status text-xs"></span>` +
    `<span class="ped-cmd-toggle text-slate-500 text-xs ml-1">▼</span>`;
  card.appendChild(hdr);

  // ── Rationale subtitle ───────────────────────────────────────────────
  if (cmd.rationale) {
    const rat = document.createElement('div');
    rat.className = 'px-4 py-1.5 text-xs text-slate-400 italic border-b border-slate-800';
    rat.textContent = cmd.rationale;
    card.appendChild(rat);
  }

  // ── Collapsible body ─────────────────────────────────────────────────
  const body = document.createElement('div');
  body.className = 'ped-card-body';

  // Fields section
  const fieldsDiv = document.createElement('div');
  fieldsDiv.className = 'px-4 py-3 flex flex-col gap-2';

  const visibleFields = cmd.fields.filter(f => _ped.mode === 'advanced' || f.required || f.value.trim() || f.added);
  visibleFields.forEach((f, fi) => {
    // Find the real index in cmd.fields for state updates
    const realIdx = cmd.fields.indexOf(f);
    fieldsDiv.appendChild(_buildFieldRow(cmd, idx, f, realIdx));
  });

  // "+ Add field" button — shows template fields not yet in the command
  if (_ped.isInbox) {
    const addBtn = document.createElement('button');
    addBtn.className = 'mt-1 text-xs text-slate-500 hover:text-slate-300 text-left transition-colors';
    addBtn.textContent = '+ Add field';
    addBtn.onclick = (e) => { e.stopPropagation(); _showAddFieldMenu(idx, addBtn); };
    fieldsDiv.appendChild(addBtn);
  }

  body.appendChild(fieldsDiv);

  // ── Inter-command notes (postNotes) ──────────────────────────────────
  const notesSection = _buildNotesSection(cmd, idx);
  body.appendChild(notesSection);

  card.appendChild(body);

  // Toggle collapse/expand on header click
  hdr.onclick = () => {
    const collapsed = body.classList.contains('hidden');
    body.classList.toggle('hidden', !collapsed);
    hdr.querySelector('.ped-cmd-toggle').textContent = collapsed ? '▼' : '▶';
  };

  _updateCardStatus(card, cmd);
  return card;
}

function _buildNotesSection(cmd, idx) {
  const wrap = document.createElement('div');
  wrap.className = 'border-t border-slate-700/40 px-4 pb-3 pt-2';

  const hasNotes = cmd.postNotes && cmd.postNotes.trim();

  if (!hasNotes && !_ped.isInbox) {
    wrap.classList.add('hidden');
    return wrap;
  }

  // Toggle button row
  const toggleRow = document.createElement('div');
  toggleRow.className = 'flex items-center gap-2';

  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'text-xs text-slate-500 hover:text-slate-300 transition-colors';
  toggleBtn.textContent = hasNotes ? '📝 Notes' : '+ Add note after this command';
  toggleRow.appendChild(toggleBtn);
  wrap.appendChild(toggleRow);

  // Notes textarea (initially hidden if no notes)
  const ta = document.createElement('textarea');
  ta.className = 'mt-2 w-full bg-slate-900 text-slate-300 text-xs rounded p-2 border border-slate-700 resize-y font-mono focus:outline-none focus:border-violet-500';
  ta.rows = 3;
  ta.placeholder = 'Add narrative, context, or instructions between this command and the next…';
  ta.dataset.notesFor = cmd.stepNum;
  ta.value = cmd.postNotes || '';
  ta.readOnly = !_ped.isInbox;
  ta.oninput = () => {
    _ped.commands[idx].postNotes = ta.value;
    _ped.dirty = true;
    _updateStatusBar();
  };

  if (!hasNotes) ta.classList.add('hidden');
  wrap.appendChild(ta);

  toggleBtn.onclick = (e) => {
    e.stopPropagation();
    const visible = !ta.classList.contains('hidden');
    ta.classList.toggle('hidden', visible);
    toggleBtn.textContent = visible
      ? '+ Add note after this command'
      : (ta.value.trim() ? '📝 Notes' : '+ Add note after this command');
    if (!visible) ta.focus();
  };

  return wrap;
}

function _buildFieldRow(cmd, cmdIdx, f, fieldIdx) {
  const isTodo = !f.value;
  const isReq  = f.required;

  const row = document.createElement('div');
  row.className = 'flex items-start gap-2';
  row.dataset.field = f.name;

  const label = document.createElement('label');
  label.className = 'text-xs text-slate-400 w-36 shrink-0 pt-1.5 leading-tight';
  label.title = f.description || '';
  label.innerHTML = _esc(f.name) + (isReq ? '<span class="text-orange-400 ml-0.5">*</span>' : '');

  let input;
  if (f.validValues && f.validValues.length) {
    input = document.createElement('select');
    input.className = `flex-1 bg-slate-900 text-slate-200 text-sm rounded px-2 py-1 border ${isReq && isTodo ? 'border-orange-600' : 'border-slate-700'}`;
    const blank = document.createElement('option');
    blank.value = ''; blank.textContent = '— choose —';
    input.appendChild(blank);
    f.validValues.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      if (v === f.value) opt.selected = true;
      input.appendChild(opt);
    });
  } else {
    input = document.createElement('input');
    input.type = 'text';
    input.className = `flex-1 bg-slate-900 text-slate-200 text-sm rounded px-2 py-1 border ${isReq && isTodo ? 'border-orange-600' : 'border-slate-700'}`;
    input.value = f.value;
    input.placeholder = isTodo && isReq ? '⚠ Required — fill in' : (f.description || '');
  }
  input.disabled = !_ped.isInbox;

  input.addEventListener('change', () => {
    _ped.commands[cmdIdx].fields[fieldIdx].value = input.value;
    _ped.dirty = true;
    const empty = !input.value.trim();
    input.className = input.className.replace(/border-\S+/g, empty && isReq ? 'border-orange-600' : 'border-slate-700');
    _updateCardStatus(input.closest('.ped-cmd-card'), _ped.commands[cmdIdx]);
    _updateStatusBar();
  });

  row.appendChild(label);
  row.appendChild(input);
  return row;
}

function _updateCardStatus(card, cmd) {
  const statusEl = card && card.querySelector('.ped-cmd-status');
  if (!statusEl) return;
  const todos = cmd.fields.filter(f => f.required && !f.value.trim()).length;
  statusEl.textContent  = todos ? `⚠ ${todos} required` : '✓';
  statusEl.className    = `ped-cmd-status text-xs ${todos ? 'text-orange-400' : 'text-emerald-400'}`;
}

function _updateStatusBar() {
  const bar = document.getElementById('ped-status-bar');
  if (!bar) return;
  const todos = _ped.commands.reduce((n, c) => n + c.fields.filter(f => f.required && !f.value.trim()).length, 0);
  const nc    = _ped.commands.length;
  const parts = [
    `${nc} command${nc !== 1 ? 's' : ''}`,
    todos
      ? `<span class="text-orange-400">${todos} required field${todos !== 1 ? 's' : ''} empty</span>`
      : '<span class="text-emerald-400">All required fields filled</span>',
    `<span class="text-slate-500">${_ped.mode === 'advanced' ? 'Advanced' : 'Basic'} template</span>`,
  ];
  if (_ped.dirty) parts.push('<span class="text-amber-400">● Unsaved</span>');
  bar.innerHTML = parts.join(' &nbsp;·&nbsp; ');
}

// ── Basic / Advanced toggle ───────────────────────────────────────────────────

async function _toggleMode() {
  _ped.mode = _ped.mode === 'basic' ? 'advanced' : 'basic';
  const modeBtn = document.getElementById('ped-mode-btn');
  if (modeBtn) modeBtn.textContent = _ped.mode === 'basic' ? 'Basic' : 'Advanced';

  // Load fields for new mode then re-enrich and re-render
  const actions = [...new Set(_ped.commands.map(c => c.action))];
  await Promise.all(actions.map(a => _fetchTemplateFields(a, _ped.mode)));
  _enrichFieldMetadata();
  _renderCommandCards();
  _updateStatusBar();
}

// ── Add optional field dropdown ───────────────────────────────────────────────

async function _showAddFieldMenu(cmdIdx, anchor) {
  const cmd      = _ped.commands[cmdIdx];
  const tmpl     = await _fetchTemplateFields(cmd.action, _ped.mode);
  const fallback = tmpl.length ? tmpl : await _fetchTemplateFields(cmd.action, 'basic');

  if (!fallback.length) {
    _showToast('No template metadata available for ' + cmd.action);
    return;
  }

  const presentNames = new Set(cmd.fields.map(f => f.name));
  const available    = fallback.filter(f => !presentNames.has(f.name));

  if (!available.length) {
    _showToast('All template fields are already in this command.');
    return;
  }

  // Remove any existing menu
  const existing = document.getElementById('ped-field-menu');
  if (existing) existing.remove();

  const menu = document.createElement('div');
  menu.id = 'ped-field-menu';
  menu.className = 'bg-slate-800 border border-slate-600 rounded shadow-xl py-1 text-sm';
  // Use inline z-index — z-70 is not a standard Tailwind class
  Object.assign(menu.style, {
    position:  'fixed',
    zIndex:    '9999',
    maxHeight: '340px',
    overflowY: 'auto',
    width:     '380px',
  });

  // Section headings: required first, then optional
  const required = available.filter(f => f.required);
  const optional = available.filter(f => !f.required);

  const addGroup = (items, label) => {
    if (!items.length) return;
    const hdr = document.createElement('div');
    hdr.className = 'px-3 pt-2 pb-0.5 text-xs font-semibold text-slate-500 uppercase tracking-wider';
    hdr.textContent = label;
    menu.appendChild(hdr);

    items.forEach(f => {
      const item = document.createElement('button');
      item.className = 'w-full text-left px-3 py-1.5 hover:bg-slate-700 text-slate-200 flex flex-col gap-0.5';
      item.innerHTML =
        `<span class="font-medium">${_esc(f.name)}${f.required ? ' <span class="text-orange-400 text-xs">*</span>' : ''}</span>` +
        (f.description ? `<span class="text-xs text-slate-500 leading-snug whitespace-normal">${_esc(f.description)}</span>` : '');
      item.onclick = () => {
        _addFieldToCommand(cmdIdx, {
          name: f.name, value: f.default_value || '', required: f.required,
          type: f.type, validValues: f.valid_values || [], description: f.description || '',
          added: true,
        });
        menu.remove();
      };
      menu.appendChild(item);
    });
  };

  addGroup(required, 'Required');
  addGroup(optional, 'Optional');

  // Position the menu near the anchor using fixed positioning
  const rect = anchor.getBoundingClientRect();
  menu.style.top  = `${Math.min(rect.bottom + 4, window.innerHeight - 350)}px`;
  menu.style.left = `${Math.min(rect.left, window.innerWidth - 396)}px`;

  document.body.appendChild(menu);

  const dismiss = e => {
    if (!menu.contains(e.target) && e.target !== anchor) {
      menu.remove();
      document.removeEventListener('click', dismiss);
    }
  };
  setTimeout(() => document.addEventListener('click', dismiss), 10);
}

function _addFieldToCommand(cmdIdx, field) {
  _ped.commands[cmdIdx].fields.push(field);
  _ped.dirty = true;
  // Re-render just this card
  const container = document.getElementById('ped-commands');
  const oldCard   = container.children[cmdIdx];
  const newCard   = _buildCommandCard(_ped.commands[cmdIdx], cmdIdx);
  container.replaceChild(newCard, oldCard);
  _updateStatusBar();
}

// ── Save ──────────────────────────────────────────────────────────────────────

async function _savePlanEdits() {
  // Flush postNotes from DOM into state before synthesising
  _ped.commands.forEach(cmd => {
    const ta = document.querySelector(`[data-notes-for="${cmd.stepNum}"]`);
    if (ta) cmd.postNotes = ta.value;
  });

  const content = _synthesizePlanMarkdown();
  const btn     = document.getElementById('ped-save-btn');
  btn.disabled  = true; btn.textContent = 'Saving…';
  try {
    const r = await fetch(`/api/plans/${encodeURIComponent(_ped.doc_id)}`, {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ content }),
    });
    if (!r.ok) throw new Error(await r.text());
    _ped.dirty = false;
    _updateStatusBar();
    btn.textContent = '✓ Saved';
    setTimeout(() => { btn.textContent = 'Save'; btn.disabled = false; }, 1500);
  } catch (e) {
    alert(`Save failed: ${e.message}`);
    btn.textContent = 'Save'; btn.disabled = false;
  }
}

// ── Validate ─────────────────────────────────────────────────────────────────

async function _validatePlanDoc() {
  if (_ped.dirty) await _savePlanEdits();

  const btn    = document.getElementById('ped-validate-btn');
  const panel  = document.getElementById('ped-validate-result');
  btn.disabled = true; btn.textContent = 'Validating…';
  panel.innerHTML = '<span class="text-slate-400">Running Dr.Egeria validate…</span>';
  panel.classList.remove('hidden');

  try {
    const r    = await fetch(`/api/plans/${encodeURIComponent(_ped.doc_id)}/validate`, { method: 'POST' });
    const data = await r.json();
    const ok   = data.status === 'ok';
    panel.innerHTML =
      `<div class="font-semibold mb-2 ${ok ? 'text-emerald-400' : 'text-red-400'}">${ok ? '✓ Validation passed' : '✗ Validation errors'}</div>` +
      `<pre class="text-xs text-slate-300 whitespace-pre-wrap">${_esc(String(data.result || ''))}</pre>`;
  } catch (e) {
    panel.innerHTML = `<span class="text-red-400">Validation request failed: ${_esc(e.message)}</span>`;
  } finally {
    btn.textContent = 'Validate'; btn.disabled = false;
  }
}

// ── Execute ───────────────────────────────────────────────────────────────────

async function _executePlanDoc() {
  if (!confirm(`Execute plan ${_ped.doc_id}?\nThis will submit all commands to Dr.Egeria.`)) return;
  if (_ped.dirty) await _savePlanEdits();
  closePlanEditor();
  if (typeof appendMessage === 'function') appendMessage('you', `execute the plan ${_ped.doc_id}`);
  if (typeof submitQuery   === 'function') submitQuery(`execute the plan ${_ped.doc_id}`, { intent_override: 'command' });
}

// ── Toast notifications ───────────────────────────────────────────────────────

function _showToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'fixed bottom-6 right-6 bg-slate-700 text-slate-100 text-sm px-4 py-2 rounded shadow-lg';
  toast.style.zIndex = '9999';
  toast.textContent  = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// ── Util ──────────────────────────────────────────────────────────────────────

function _esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
