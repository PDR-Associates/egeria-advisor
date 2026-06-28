/**
 * report_spec_canvas.js — Report Spec Canvas built on ArtifactCanvas
 *
 * Adapts ArtifactCanvas for report spec drafts:
 *   data shape: report spec draft (columns + three parameter categories)
 *   sync:       PATCH /api/reports/drafts/{id}/columns
 *   fields:     GET  /api/templates/Column/fields
 */

// ── Parameter section definitions ──────────────────────────────────────────
const _PARAM_SECTIONS = [
  {
    id: 'content_filters',
    label: 'Content Filters',
    open: true,
    fields: [
      { key: 'search_string',              label: 'Search string',       type: 'text',   placeholder: '*' },
      { key: 'starts_with',                label: 'Starts with',         type: 'checkbox' },
      { key: 'ends_with',                  label: 'Ends with',           type: 'checkbox' },
      { key: 'ignore_case',                label: 'Ignore case',         type: 'checkbox' },
      { key: 'metadata_element_type',      label: 'Element type',        type: 'text',   placeholder: 'e.g. dataHub' },
      { key: 'metadata_element_subtypes',  label: 'Subtypes',            type: 'text',   placeholder: 'comma-separated subtypes' },
      { key: 'limit_results_by_status',    label: 'Status filter',       type: 'select',
        options: ['', 'ACTIVE', 'DRAFT', 'DEPRECATED', 'PROPOSED', 'APPROVED', 'DELETED'] },
      { key: 'governance_zone_filter',     label: 'Governance zone',     type: 'text',   placeholder: 'zone name' },
      { key: 'anchor_type_name',           label: 'Anchor type',         type: 'text',   placeholder: 'e.g. Asset' },
      { key: 'anchor_domain',              label: 'Anchor domain',       type: 'text',   placeholder: 'domain name' },
    ],
  },
  {
    id: 'shape_defaults',
    label: 'Shape Defaults',
    open: false,
    fields: [
      { key: 'sequencing_property',        label: 'Sort field',          type: 'text',   placeholder: 'display_name' },
      { key: 'sequencing_order',           label: 'Sort order',          type: 'select', options: ['', 'ASC', 'DESC'] },
      { key: 'graph_query_depth',          label: 'Graph depth',         type: 'number', placeholder: '0' },
      { key: 'max_mermaid_node_count',     label: 'Max diagram nodes',   type: 'number', placeholder: '50' },
      { key: 'skip_relationships',         label: 'Skip relationships',  type: 'checkbox' },
      { key: 'include_only_relationships', label: 'Only relationships',  type: 'text',   placeholder: 'comma-separated rel types' },
    ],
  },
  {
    id: 'performance_hints',
    label: 'Performance Hints',
    open: false,
    fields: [
      { key: 'page_size',               label: 'Page size',          type: 'number', placeholder: '100' },
      { key: 'start_from',              label: 'Start from',         type: 'number', placeholder: '0' },
      { key: 'relationship_page_size',  label: 'Rel. page size',     type: 'number', placeholder: '50' },
      { key: 'as_of_time',              label: 'As of time',         type: 'text',   placeholder: 'ISO timestamp' },
      { key: 'effective_time',          label: 'Effective time',     type: 'text',   placeholder: 'ISO timestamp' },
    ],
  },
];

// Debounce helper
function _debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// PATCH a single parameter category
async function _patchReportParams(draftId, category, values) {
  try {
    await fetch(`/api/reports/drafts/${encodeURIComponent(draftId)}/columns`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...Auth.getHeaders() },
      body: JSON.stringify({ [category]: values }),
    });
  } catch (e) {
    console.warn('patchReportParams failed', e);
  }
}

// Render editable Spec Info (target_type, heading) above param sections
function _renderSpecInfo(meta, draftId) {
  const container = document.getElementById('rcanvas-params');
  if (!container) return;

  const debouncedPatch = _debounce(async () => {
    const ttEl = container.querySelector('[data-spec-key="target_type"]');
    const hdEl = container.querySelector('[data-spec-key="heading"]');
    const afEl = container.querySelector('[data-spec-key="action_function"]');
    const body = {};
    if (ttEl && ttEl.value.trim()) body.target_type = ttEl.value.trim();
    if (hdEl && hdEl.value.trim()) body.heading = hdEl.value.trim();
    if (afEl) body.action_function = afEl.value.trim();
    if (Object.keys(body).length) {
      try {
        await fetch(`/api/reports/drafts/${encodeURIComponent(draftId)}/columns`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ...Auth.getHeaders() },
          body: JSON.stringify(body),
        });
      } catch (e) { console.warn('spec info patch failed', e); }
    }
  }, 600);

  const details = document.createElement('details');
  details.className = 'border-b border-slate-700/50';
  details.open = true;
  details.innerHTML = `<summary class="px-3 py-1.5 text-xs font-semibold text-slate-400 hover:text-slate-200 cursor-pointer select-none list-none flex items-center gap-1"><span class="text-slate-500 text-[10px]">▸</span> Spec Info</summary>`;

  const body = document.createElement('div');
  body.className = 'px-3 pb-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 items-center';

  [
    { key: 'target_type',     label: 'Target type',     value: meta.target_type || '',     placeholder: 'e.g. Collection, Glossary' },
    { key: 'heading',         label: 'Heading',         value: meta.answers?.Heading || '', placeholder: 'Report title' },
    { key: 'action_function', label: 'Action function', value: meta.action_function || '', placeholder: 'e.g. GlossaryManager.find_glossaries' },
  ].forEach(f => {
    const lbl = document.createElement('label');
    lbl.className = 'text-[11px] text-slate-500 whitespace-nowrap';
    lbl.textContent = f.label;
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.className = 'text-[11px] bg-slate-700 border border-slate-600 rounded px-1.5 py-0.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500 w-full';
    inp.placeholder = f.placeholder;
    inp.value = f.value;
    inp.dataset.specKey = f.key;
    inp.addEventListener('input', debouncedPatch);
    body.appendChild(lbl);
    body.appendChild(inp);
  });

  details.appendChild(body);
  container.insertAdjacentElement('afterbegin', details);
}

// Render all three parameter sections into #rcanvas-params
function _renderParamSections(meta, draftId) {
  const container = document.getElementById('rcanvas-params');
  if (!container) return;
  container.innerHTML = '';

  _renderSpecInfo(meta, draftId);

  _PARAM_SECTIONS.forEach(section => {
    const values = meta[section.id] || {};

    const details = document.createElement('details');
    details.className = 'border-b border-slate-700/50 last:border-0';
    if (section.open) details.open = true;

    const summary = document.createElement('summary');
    summary.className =
      'px-3 py-1.5 text-xs font-semibold text-slate-400 hover:text-slate-200 cursor-pointer ' +
      'select-none list-none flex items-center gap-1';
    summary.innerHTML =
      `<span class="text-slate-500 text-[10px]">▸</span> ${section.label}`;
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'px-3 pb-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 items-center';

    const debouncedPatch = _debounce(() => {
      // Collect current values from all inputs in this section
      const updated = {};
      section.fields.forEach(f => {
        const el = body.querySelector(`[data-param-key="${f.key}"]`);
        if (!el) return;
        if (f.type === 'checkbox') {
          if (el.checked) updated[f.key] = true;
        } else {
          const v = el.value.trim();
          if (v !== '' && v !== (f.placeholder || '')) {
            updated[f.key] = f.type === 'number' ? Number(v) : v;
          }
        }
      });
      _patchReportParams(draftId, section.id, updated);
    }, 600);

    section.fields.forEach(f => {
      const lbl = document.createElement('label');
      lbl.className = 'text-[11px] text-slate-500 whitespace-nowrap';
      lbl.textContent = f.label;

      let input;
      if (f.type === 'select') {
        input = document.createElement('select');
        input.className =
          'text-[11px] bg-slate-700 border border-slate-600 rounded px-1.5 py-0.5 ' +
          'text-slate-200 focus:outline-none focus:border-violet-500 w-full';
        (f.options || []).forEach(opt => {
          const o = document.createElement('option');
          o.value = opt; o.textContent = opt || '(any)';
          if (String(values[f.key] ?? '') === opt) o.selected = true;
          input.appendChild(o);
        });
      } else if (f.type === 'checkbox') {
        input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'accent-violet-500';
        input.checked = !!values[f.key];
      } else {
        input = document.createElement('input');
        input.type = f.type || 'text';
        input.className =
          'text-[11px] bg-slate-700 border border-slate-600 rounded px-1.5 py-0.5 ' +
          'text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500 w-full';
        input.placeholder = f.placeholder || '';
        const cur = values[f.key];
        if (cur !== undefined && cur !== null) input.value = String(cur);
      }

      input.dataset.paramKey = f.key;
      input.addEventListener('change', debouncedPatch);
      input.addEventListener('input', debouncedPatch);

      body.appendChild(lbl);
      body.appendChild(input);
    });

    details.appendChild(body);
    container.appendChild(details);
  });
}

// ── ArtifactCanvas adapter ──────────────────────────────────────────────────

const _reportAdapter = {
  async fetch(draftId) {
    const r = await fetch(`/api/reports/drafts/${encodeURIComponent(draftId)}`, { headers: Auth.getHeaders() });
    if (!r.ok) throw new Error(`Report draft ${draftId} not found`);
    const spec = await r.json();
    return {
      title: spec.answers?.Heading || spec.title || 'Untitled Report Spec',
      items: spec.columns || [],
      meta: {
        id: draftId,
        doc_id: spec.doc_id,
        answers: spec.answers || {},
        action_function: spec.action_function,
        target_type: spec.target_type,
        content_filters:   spec.content_filters   || { search_string: '*' },
        shape_defaults:    spec.shape_defaults     || {},
        performance_hints: spec.performance_hints  || { page_size: 100, start_from: 0 },
      },
    };
  },

  async patch(draftId, items) {
    await fetch(`/api/reports/drafts/${encodeURIComponent(draftId)}/columns`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...Auth.getHeaders() },
      body: JSON.stringify({ columns: items }),
    });
  },

  fieldUrl(action, mode) {
    return `/api/templates/${encodeURIComponent(action)}/fields`;
  },
};

const _reportItemAdapter = {
  getType(col) {
    return 'Column';
  },

  getDisplayName(col) {
    return col.name || 'Unnamed Column';
  },

  getParams(col) {
    const result = {};
    if (col.key) result['Key'] = col.key;
    const fmt = col.format;
    if (fmt !== undefined && fmt !== false && fmt !== 'False' && fmt !== '') {
      result['Apply formatting'] = String(fmt);
    }
    if (col.detail_spec) result['Detail Spec'] = col.detail_spec;
    if (col.formats && col.formats !== 'ALL') result['Output types'] = col.formats;
    return result;
  },

  getNarrative(col) {
    return col.description || '';
  },

  setNarrative(col, v) {
    col.description = v;
  },

  getFieldValues(col) {
    const fmt = col.format;
    return {
      'Name': col.name || '',
      'Key': col.key || '',
      'Apply formatting': (fmt === true || fmt === 'True') ? 'True' : (fmt && fmt !== 'False') ? String(fmt) : '',
      'Detail Spec': col.detail_spec || '',
      'Output types': col.formats || 'ALL',
    };
  },

  setFieldValue(col, name, v) {
    if (name === 'Name') {
      col.name = v;
    } else if (name === 'Key') {
      col.key = v;
    } else if (name === 'Apply formatting') {
      if (!v || v === 'False' || v === 'false') {
        col.format = false;
      } else if (v === 'True' || v === 'true') {
        col.format = true;
      } else {
        col.format = v;
      }
    } else if (name === 'Detail Spec') {
      col.detail_spec = v || null;
    } else if (name === 'Output types') {
      col.formats = v || 'ALL';
    }
  },

  makeNew(typeName, keyOverride) {
    const name = typeName || 'New Column';
    return {
      name,
      key: keyOverride || name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, ''),
      format: false,
      detail_spec: null,
      formats: 'ALL',
    };
  }
};

const ReportSpecCanvas = (() => {
  let _canvas = null;
  let _draftId = null;

  function _ensureCanvas() {
    if (_canvas) return _canvas;
    _canvas = new ArtifactCanvas({
      panelId: 'report-canvas-panel',
      handleId: 'resize-chat-report-canvas',
      cardsId: 'rcanvas-cards',
      titleId: 'rcanvas-title',
      modeButtonId: 'rcanvas-mode-btn',
      adapter: _reportAdapter,
      itemAdapter: _reportItemAdapter,
      addItemFn(doAdd) {
        // Open the column-name modal instead of the Dr.Egeria command picker
        if (typeof openAddColumnModal === 'function') {
          openAddColumnModal((name, key) => doAdd(name, key));
        } else {
          const name = prompt('Column display name (e.g. "Description", "Owner"):');
          if (name?.trim()) doAdd(name.trim());
        }
      },
      onRender(data) {
        const docId = data?.meta?.doc_id;
        const titleEl = document.getElementById('rcanvas-title');
        if (titleEl) titleEl.dataset.docId = docId || '';

        // Render the three parameter sections
        if (data?.meta && _draftId) {
          _renderParamSections(data.meta, _draftId);
        }

        // Toggles Generate vs. Execute buttons
        document.getElementById('rcanvas-generate-btn')?.classList.remove('hidden');
        document.getElementById('rcanvas-execute-btn')?.classList.toggle('hidden', !docId);
        document.getElementById('rcanvas-format-select')?.classList.toggle('hidden', !docId);
      },
    });
    return _canvas;
  }

  async function open(draftId) {
    _draftId = draftId;
    await _ensureCanvas().open(draftId);
    PlanCanvas.close();
  }

  function close() {
    _draftId = null;
    if (_canvas) _canvas.close();
  }

  async function refresh(draftId) {
    await _ensureCanvas().refresh(draftId || _draftId);
  }

  async function addColumn() {
    await _ensureCanvas().addItem();
  }

  return { open, close, refresh, addColumn };
})();
