/**
 * plan_canvas.js — Plan Canvas built on ArtifactCanvas
 *
 * Adapts ArtifactCanvas for the plan draft artifact type:
 *   data shape: draft spec (commands_identified, answers, title, doc_id)
 *   sync:       PATCH /api/drafts/{id}/commands
 *   fields:     GET  /api/templates/{action}/fields?level={mode}
 */

// ── Plan-specific data adapter ────────────────────────────────────────────────

const _planAdapter = {
  async fetch(draftId) {
    const r = await fetch(`/api/drafts/${encodeURIComponent(draftId)}`);
    if (!r.ok) throw new Error(`draft ${draftId} not found`);
    const spec = await r.json();
    // Normalise to ArtifactCanvas shape
    return {
      title: spec.title || '',
      items: spec.commands_identified || [],
      meta:  { id: draftId, doc_id: spec.doc_id, answers: spec.answers || {} },
    };
  },

  async patch(draftId, items) {
    await fetch(`/api/drafts/${encodeURIComponent(draftId)}/commands`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ commands: items }),
    });
  },

  fieldUrl(action, mode) {
    return `/api/templates/${encodeURIComponent(action)}/fields?level=${mode || 'basic'}`;
  },
};

// ── Plan-specific item adapter ────────────────────────────────────────────────

const _planItemAdapter = {
  getType(cmd)        { return cmd.action || ''; },
  getDisplayName(cmd) {
    return cmd.pre_filled?.['Display Name'] || cmd.display_name || '';
  },
  getParams(cmd) {
    // Show pre_filled fields other than Display Name as chips
    const result = {};
    for (const [k, v] of Object.entries(cmd.pre_filled || {})) {
      if (k !== 'Display Name' && v) result[k] = v;
    }
    return result;
  },
  getNarrative(cmd)        { return cmd.narrative || ''; },
  setNarrative(cmd, v)     { cmd.narrative = v; },
  getFieldValues(cmd)      {
    return { ...(cmd.pre_filled || {}), 'Display Name': cmd.display_name || '' };
  },
  setFieldValue(cmd, name, v) {
    if (!cmd.pre_filled) cmd.pre_filled = {};
    cmd.pre_filled[name] = v;
    if (name === 'Display Name') cmd.display_name = v;
  },
  makeNew(typeName) {
    return {
      action:       typeName,
      display_name: '',
      description:  '',
      rationale:    '',
      narrative:    '',
      pre_filled:   {},
      placeholders: {},
    };
  },
};

// ── PlanCanvas singleton ──────────────────────────────────────────────────────

const PlanCanvas = (() => {
  let _canvas = null;
  let _draftId = null;

  function _ensureCanvas() {
    if (_canvas) return _canvas;
    _canvas = new ArtifactCanvas({
      panelId:      'plan-canvas-panel',
      handleId:     'resize-chat-canvas',
      cardsId:      'pcanvas-cards',
      titleId:      'pcanvas-title',
      modeButtonId: 'pcanvas-mode-btn',
      adapter:      _planAdapter,
      itemAdapter:  _planItemAdapter,
      onRender(data) {
        // Show Execute button when plan document has been generated
        const execBtn = document.getElementById('pcanvas-execute-btn');
        if (execBtn) {
          const docId = data?.meta?.doc_id;
          execBtn.classList.toggle('hidden', !docId);
          const titleEl = document.getElementById('pcanvas-title');
          if (titleEl) titleEl.dataset.docId = docId || '';
        }
      },
    });
    return _canvas;
  }

  async function open(draftId) {
    _draftId = draftId;
    await _ensureCanvas().open(draftId);
  }

  function close() {
    _draftId = null;
    if (_canvas) _canvas.close();
  }

  async function refresh(draftId) {
    await _ensureCanvas().refresh(draftId || _draftId);
  }

  async function addStep() {
    await _ensureCanvas().addItem();
  }

  function toggleMode() {
    _ensureCanvas().toggleMode();
  }

  return { open, close, refresh, addStep, toggleMode };
})();
