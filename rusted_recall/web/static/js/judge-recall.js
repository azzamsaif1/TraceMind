/* Rusted Recall — Judge Experience.
 *
 * Preserves the orbital "Living Brand Intelligence" visual identity of the
 * approved design, but every value shown is REAL persisted Rusted Recall state
 * injected by the server (window #judge-data) or fetched from the thin
 * /api/judge/... adapter. There is NO hard-coded demo data and NO simulated
 * completion: the triumph state only appears when the recall is genuinely
 * verified, and animations visualise the actual classifications/jobs.
 */
(function () {
    'use strict';

    const bootEl = document.getElementById('judge-data');
    let data = JSON.parse(bootEl.textContent);
    const RECALL_ID = data.recall_id;
    const API = '/api/judge/recalls/' + encodeURIComponent(RECALL_ID);

    // ---- DOM ----
    const $ = (id) => document.getElementById(id);
    const app = $('app');
    const orbit = $('orbit');
    const timelineEl = $('timeline');
    const depPathSvg = $('depPath');
    const ghostLayer = $('ghostLayer');
    const dotGrid = $('dotGrid');
    const orbitalParticles = $('orbitalParticles');
    const gaugeProgress = $('gaugeProgress');
    const gaugeValue = $('gaugeValue');
    const shockwaveLayer = $('shockwaveLayer');
    const reverseWave = $('reverseWave');
    const milestones = $('milestones');
    const progressDots = $('progressDots');
    const progressFill = $('progressFill');
    const timeStatus = $('timeStatus');
    const timerDisplay = $('timerDisplay');
    const triumph = $('triumph');
    const orbitStage = $('orbit');
    const drawer = $('drawer');

    let nodes = [];
    let ghosts = [];
    let selectedAssetId = null;
    let pollTimer = null;
    let replaying = false;

    // ---- static journey progress by real status ----
    const STATUS_PROGRESS = {
        draft: 10, analysing: 40, ready_for_review: 60, approved: 70,
        repairing: 85, partially_completed: 90, completed: 100,
        failed: 90, blocked: 55,
    };
    const STATUS_DOT = {
        completed: 'completed', partially_completed: 'running', repairing: 'running',
        analysing: 'running', failed: 'critical', blocked: 'critical',
    };

    // ---- background particles (visual only) ----
    function createParticles() {
        const c = $('particles');
        for (let i = 0; i < 50; i++) {
            const p = document.createElement('div');
            p.className = 'particle';
            p.style.left = Math.random() * 100 + '%';
            p.style.width = (1 + Math.random() * 3) + 'px';
            p.style.height = p.style.width;
            p.style.animationDuration = (10 + Math.random() * 25) + 's';
            p.style.animationDelay = (Math.random() * 20) + 's';
            p.style.opacity = 0.1 + Math.random() * 0.25;
            c.appendChild(p);
        }
    }
    function createOrbitalParticles() {
        const count = 24;
        orbitalParticles.innerHTML = '';
        for (let i = 0; i < count; i++) {
            const p = document.createElement('div');
            p.className = 'orbital-particle';
            const size = 2 + Math.random() * 4;
            const duration = 8 + Math.random() * 12;
            const delay = Math.random() * duration;
            const radius = 120 + Math.random() * 60;
            p.style.width = size + 'px';
            p.style.height = size + 'px';
            p.style.animation = `j-orbital-${i} ${duration}s linear infinite`;
            p.style.animationDelay = '-' + delay + 's';
            const style = document.createElement('style');
            style.textContent = `@keyframes j-orbital-${i}{0%{transform:rotate(0deg) translateX(${radius}px) rotate(0deg);}100%{transform:rotate(360deg) translateX(${radius}px) rotate(-360deg);}}`;
            document.head.appendChild(style);
            orbitalParticles.appendChild(p);
        }
    }

    // ---- 3D tilt ----
    document.addEventListener('mousemove', (e) => {
        const rect = app.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width - 0.5;
        const y = (e.clientY - rect.top) / rect.height - 0.5;
        app.style.transform = `rotateX(${-y * 2.5}deg) rotateY(${x * 2.5}deg)`;
        if (dotGrid) dotGrid.style.transform = `translate(${x * -4}px, ${y * -4}px)`;
    });
    document.addEventListener('mouseleave', () => {
        app.style.transform = 'rotateX(0deg) rotateY(0deg)';
        if (dotGrid) dotGrid.style.transform = 'translate(0,0)';
    });

    // ---- positioning ----
    function getPositions(count) {
        const rect = $('stage').getBoundingClientRect();
        const w = rect.width || 580, h = rect.height || 420;
        const cx = w / 2, cy = h / 2;
        const radius = Math.min(w, h) * 0.34;
        const step = (2 * Math.PI) / Math.max(1, count);
        const start = -Math.PI / 2;
        const out = [];
        for (let i = 0; i < count; i++) {
            const a = start + i * step;
            out.push({ x: cx + Math.cos(a) * radius, y: cy + Math.sin(a) * radius });
        }
        return out;
    }

    function intensityOf(asset) {
        // Real magnitude straight from the persisted impact score (0..1).
        return asset.impact_score != null ? Math.round(asset.impact_score * 100) : 0;
    }

    // ---- render orbital nodes from REAL assets ----
    function renderAssets() {
        orbit.innerHTML = '';
        ghostLayer.innerHTML = '';
        const positions = getPositions(data.assets.length);

        ghosts = data.assets.map((asset, i) => {
            const pos = positions[i];
            const el = document.createElement('div');
            el.className = 'asset-ghost';
            el.style.left = pos.x + 'px';
            el.style.top = pos.y + 'px';
            el.innerHTML = `<span class="preview">${asset.icon}</span><span class="name">${escapeHtml(asset.name)}</span><span class="label">previous</span>`;
            ghostLayer.appendChild(el);
            return { id: asset.id, el, x: pos.x, y: pos.y };
        });

        nodes = data.assets.map((asset, i) => {
            const pos = positions[i];
            const intensity = intensityOf(asset);
            const ic = intensity > 70 ? 'high' : intensity > 40 ? 'mid' : intensity > 10 ? 'low' : '';
            const el = document.createElement('div');
            el.className = `asset-node ${asset.node_status}`;
            el.dataset.id = asset.id;
            el.style.left = pos.x + 'px';
            el.style.top = pos.y + 'px';
            el.innerHTML = `
                <span class="intensity-ring ${intensity > 0 ? 'active ' + ic : ''}"></span>
                <span class="preview">${asset.icon}</span>
                <span class="name">${escapeHtml(asset.name)}</span>
                <span class="status-tag">${(asset.classification || asset.node_status || '').toUpperCase()}</span>`;
            el.addEventListener('click', () => { selectAsset(asset.id); openDrawer(asset.id); });
            el.addEventListener('mouseenter', () => showGhost(asset.id, true));
            el.addEventListener('mouseleave', () => showGhost(asset.id, false));
            orbit.appendChild(el);
            return { id: asset.id, el, x: pos.x, y: pos.y, intensity, status: asset.node_status };
        });
    }

    function showGhost(id, show) {
        const g = ghosts.find((x) => x.id === id);
        if (!g) return;
        if (show) { g.el.classList.add('visible'); drawDependencyPath(id); }
        else { g.el.classList.remove('visible'); if (selectedAssetId !== id) depPathSvg.classList.remove('active'); }
    }

    function drawDependencyPath(id) {
        const asset = data.assets.find((a) => a.id === id);
        const rect = $('stage').getBoundingClientRect();
        const cx = rect.width / 2, cy = rect.height / 2;
        const coords = [{ x: cx, y: cy }];
        // Resolve real dependency-path entries to orbit nodes where possible.
        const path = (asset && asset.dependency_path) || [];
        path.forEach((entry) => {
            const key = String(entry).replace(/^asset:/, '').replace(/^sot:.*/, 'source');
            if (key === 'source') return;
            const n = nodes.find((nn) => nn.id === key)
                || nodes.find((nn) => { const a = data.assets.find((x) => x.id === nn.id); return a && a.name === entry; });
            if (n) coords.push({ x: n.x, y: n.y });
        });
        const target = nodes.find((n) => n.id === id);
        if (target && (coords.length === 0 || coords[coords.length - 1].x !== target.x)) coords.push({ x: target.x, y: target.y });
        if (coords.length < 2) { depPathSvg.classList.remove('active'); return; }
        let svg = '';
        for (let i = 0; i < coords.length - 1; i++) {
            const hl = i === coords.length - 2 ? 'highlight' : '';
            svg += `<line x1="${coords[i].x}" y1="${coords[i].y}" x2="${coords[i + 1].x}" y2="${coords[i + 1].y}" class="${hl}" />`;
        }
        depPathSvg.innerHTML = svg;
        depPathSvg.classList.add('active');
    }

    function selectAsset(id) {
        selectedAssetId = id;
        drawDependencyPath(id);
        ghosts.forEach((g) => g.el.classList.toggle('visible', g.id === id));
    }

    // ---- gauge / stats ----
    function updateGauge(percent) {
        const circ = 157.08;
        gaugeProgress.style.strokeDashoffset = circ - (percent / 100) * circ;
        gaugeValue.textContent = Math.round(percent);
        let color = '#22c55e';
        if (percent > 70) color = '#ef4444';
        else if (percent > 40) color = '#facc15';
        else if (percent > 15) color = '#F97316';
        gaugeProgress.style.stroke = color;
    }

    function updateLiveStats() {
        const s = data.summary || {};
        $('statAffected').textContent = s.affected != null ? s.affected : 0;
        $('statRepaired').textContent = s.repaired != null ? s.repaired : 0;
        $('statSaved').textContent = s.operations_avoided != null ? s.operations_avoided : 0;
        $('statOpps').textContent = s.verified_opportunities != null ? s.verified_opportunities : 0;
        const total = data.assets.length || 1;
        updateGauge(((s.affected || 0) / total) * 100);
    }

    // ---- timeline ----
    function renderTimeline(activeIndex) {
        timelineEl.innerHTML = '';
        (data.timeline || []).forEach((item, idx) => {
            const li = document.createElement('li');
            const isActive = activeIndex !== undefined ? idx === activeIndex : idx === data.timeline.length - 1;
            const isDone = activeIndex !== undefined ? idx < activeIndex : false;
            li.className = (isActive ? 'active' : '') + (isDone ? ' done' : '');
            li.innerHTML = `<span class="event-dot"></span><span class="time">${escapeHtml(item.time)}</span><span class="event">${escapeHtml(item.event)}</span>`;
            timelineEl.appendChild(li);
        });
    }

    function renderMilestones() {
        milestones.innerHTML = '';
        [['Start', 0], ['Detect', 25], ['Analyze', 50], ['Repair', 75], ['Complete', 100]].forEach(([label, pos]) => {
            const done = pos <= (STATUS_PROGRESS[data.status] || 0);
            const el = document.createElement('div');
            el.className = 'milestone' + (done ? ' active' : '');
            el.style.left = pos + '%';
            el.innerHTML = `<span class="tooltip">${label}</span>`;
            milestones.appendChild(el);
        });
    }

    function renderProgressDots() {
        progressDots.innerHTML = '';
        for (let i = 0; i < 8; i++) {
            const d = document.createElement('div');
            d.className = 'dot-particle';
            d.style.left = (i / 8) * 100 + '%';
            d.style.animationDuration = (3 + Math.random() * 2) + 's';
            d.style.animationDelay = (Math.random() * 2) + 's';
            progressDots.appendChild(d);
        }
    }

    // ---- header / sidebar / footer from real state ----
    function updateInfo() {
        const src = data.source || {};
        $('recallId').textContent = RECALL_ID.slice(0, 12);
        $('recallName').innerHTML = `${escapeHtml(src.name || 'Recall')}<br /><span class="sub">${escapeHtml(src.current_claim || '')}</span>`;
        $('sourceLabel').textContent = src.name || 'Source of Truth';
        $('currentClaim').textContent = src.current_claim || '—';
        if (src.previous_claim) {
            $('changedWrap').style.display = '';
            $('previousClaim').textContent = src.previous_claim;
        } else {
            $('changedWrap').style.display = 'none';
        }
        const statusLabel = prettyStatus(data.status);
        $('statusLabel').textContent = statusLabel;
        $('statusBadge').textContent = statusLabel;
        $('statusBadge').className = 'status-badge ' + (STATUS_DOT[data.status] || 'idle');
        $('statusDot').className = 'dot ' + (STATUS_DOT[data.status] || '');
        $('currentOp').innerHTML = `${escapeHtml(data.current_operation || '—')}<span class="cursor-blink"></span>`;

        const prog = STATUS_PROGRESS[data.status] || 20;
        progressFill.style.width = prog + '%';
        progressFill.className = 'fill' + (data.status === 'completed' ? ' completed' : (STATUS_DOT[data.status] === 'running' ? ' running' : ''));
        timeStatus.textContent = data.current_operation || statusLabel;
        timeStatus.className = 'status-label' + (data.status === 'completed' ? ' completed' : (STATUS_DOT[data.status] === 'running' ? ' running' : ''));
        timerDisplay.textContent = elapsedSince(data.created_at);

        const pa = data.primary_action || { label: '—', action: 'none', enabled: false };
        const btn = $('btnPrimary');
        btn.textContent = pa.label;
        btn.disabled = !pa.enabled;
        btn.dataset.action = pa.action;
    }

    // ---- triumph (only when genuinely verified) ----
    function updateTriumph() {
        const verified = data.status === 'completed';
        if (!verified) { triumph.style.display = 'none'; orbitStage.classList.remove('breathing'); return; }
        const s = data.summary || {};
        $('tAssets').textContent = s.assets_analysed || 0;
        $('tAffected').textContent = s.affected || 0;
        $('tRepaired').textContent = s.repaired || 0;
        $('tReview').textContent = s.requiring_review || 0;
        $('tSaved').textContent = s.operations_avoided || 0;
        $('tOpps').textContent = s.verified_opportunities || 0;
        // Only claim B2 verification when the engine actually stored + hashed it.
        $('triumphVerdict').textContent = s.storage_verified ? 'Stored on B2 · Verified' : 'Recall verified';
        triumph.style.display = 'flex';
        orbitStage.classList.add('breathing');
    }

    // ---- opportunities ----
    function renderOpportunities() {
        const list = $('oppList');
        list.innerHTML = '';
        const opps = data.opportunities || [];
        if (!opps.length) {
            list.innerHTML = '<div class="j-empty">No verified opportunities yet.' +
                (data.status === 'completed' ? ' Use “Discover Verified Opportunities”.' : '') + '</div>';
            return;
        }
        opps.forEach((o) => {
            if (o.status === 'rejected') return; // rejected only under technical evidence
            const div = document.createElement('div');
            div.className = 'j-opp';
            const why = o.why_enabled || (o.counterfactual ? 'Not valid before the verified change.' : '');
            div.innerHTML = `
                <div class="j-opp-title">${escapeHtml(o.title || o.kind || 'Opportunity')}</div>
                <div class="j-opp-sub">${escapeHtml(o.rationale || '')}</div>
                ${why ? `<div class="j-opp-sub">${escapeHtml(why)}</div>` : ''}
                <span class="j-opp-status ${o.status}">${o.status}</span>`;
            if (o.executable) {
                const b = document.createElement('button');
                b.className = 'btn btn-success';
                b.textContent = 'Execute';
                b.addEventListener('click', () => executeOpportunity(o.id, b));
                div.appendChild(b);
            } else if (o.result) {
                const r = document.createElement('div');
                r.className = 'j-opp-sub';
                r.textContent = `Result: ${o.result.executed || 0} executed, ${o.result.blocked || 0} blocked.`;
                div.appendChild(r);
            }
            list.appendChild(div);
        });
    }

    // ---- drawer ----
    async function openDrawer(assetId) {
        let a = data.assets.find((x) => x.id === assetId);
        try {
            const res = await fetch(`${API}/assets/${encodeURIComponent(assetId)}`);
            if (res.ok) a = await res.json();
        } catch (e) { /* fall back to cached row */ }
        if (!a) return;
        $('drawerTitle').textContent = `${a.icon} ${a.name}`;
        $('dClass').textContent = a.classification || '—';
        $('dImpact').textContent = a.impact_score != null ? a.impact_score : '—';
        $('dPath').textContent = (a.dependency_path && a.dependency_path.length) ? a.dependency_path.join(' → ') : '—';
        $('dMethod').textContent = a.derivation_method ? a.derivation_method : (a.repair_requirement || '—');
        $('dStatus').textContent = a.job_status || '—';
        $('dError').textContent = a.error_category || '—';
        $('dB2').textContent = a.b2_key ? shorten(a.b2_key) : '—';
        $('dVersions').textContent = a.versions || '—';
        $('dEvidence').textContent = a.sha256 ? a.sha256.slice(0, 12) + '…' : '—';
        const cw = $('dCausalWrap');
        if (a.causal_reason) { cw.style.display = ''; $('dCausal').textContent = a.causal_reason; }
        else cw.style.display = 'none';
        // before/after
        const pv = $('drawerPreview');
        if (a.before_url || a.after_url) {
            pv.style.display = 'flex';
            toggleImg($('dBefore'), a.before_url);
            toggleImg($('dAfter'), a.after_url);
        } else pv.style.display = 'none';
        // review actions only while a decision can still change the outcome
        const canReview = ['directly_affected', 'probably_affected', 'needs_review', 'requires_review'].includes(a.classification)
            && a.job_status !== 'completed';
        const ra = $('reviewActions');
        ra.style.display = canReview ? 'flex' : 'none';
        ra.querySelectorAll('button').forEach((b) => { b.onclick = () => submitReview(assetId, b.dataset.decision); });
        drawer.classList.add('open');
    }
    function toggleImg(img, url) { if (url) { img.src = url; img.style.display = ''; } else { img.removeAttribute('src'); img.style.display = 'none'; } }

    $('closeDrawer').addEventListener('click', () => drawer.classList.remove('open'));

    async function submitReview(assetId, decision) {
        const fd = new FormData();
        fd.append('decision', decision);
        if (decision === 'mark_safe') fd.append('new_classification', 'safe');
        try {
            await fetch(`${API}/assets/${encodeURIComponent(assetId)}/review`, { method: 'POST', body: fd });
        } catch (e) { /* keep UI honest; refresh will reflect reality */ }
        await refreshState();
        // A valid approval is what authorises repair (spec: "repair starts only
        // after valid approval"). Exclude / mark-safe only record the decision.
        if (decision === 'approve') { drawer.classList.remove('open'); startRepair(); }
        else openDrawer(assetId);
    }

    // ---- repair (real engine + polling) ----
    async function startRepair() {
        try { await fetch(`${API}/repair`, { method: 'POST' }); } catch (e) { return; }
        triggerShockwave();
        startPolling();
    }
    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(async () => {
            let st;
            try { st = await (await fetch(`${API}/status`)).json(); } catch (e) { return; }
            data.status = st.recall_status;
            data.assets = st.assets;
            data.timeline = st.timeline;
            data.summary = st.summary;
            renderAssets(); renderTimeline(); renderMilestones(); updateInfo(); updateLiveStats(); updateTriumph();
            if (!st.active) { clearInterval(pollTimer); pollTimer = null; if (data.status === 'completed') triggerReverseWave(); }
        }, 1500);
    }

    // ---- opportunities discover/execute ----
    async function discover() {
        try {
            const res = await fetch(`${API}/opportunities/discover`, { method: 'POST' });
            const body = await res.json();
            data.opportunities = body.opportunities || [];
        } catch (e) { /* noop */ }
        await refreshState();
    }
    async function executeOpportunity(id, btn) {
        if (btn) { btn.disabled = true; btn.textContent = 'Executing…'; }
        try {
            const res = await fetch(`${API}/opportunities/${encodeURIComponent(id)}/execute`, { method: 'POST' });
            const body = await res.json();
            data.opportunities = body.opportunities || data.opportunities;
        } catch (e) { /* noop */ }
        await refreshState();
    }

    // ---- evidence modal ----
    async function openEvidence() {
        let ev;
        try { ev = await (await fetch(`${API}/evidence`)).json(); } catch (e) { return; }
        const s = ev.summary || {};
        const body = $('evidenceBody');
        const row = (k, v) => `<div class="row"><span class="k">${k}</span><span>${v}</span></div>`;
        body.innerHTML = `
            <div class="j-ev-group"><h4>What changed</h4>
                ${row('Source', escapeHtml((data.source || {}).name || '—'))}
                ${row('New', escapeHtml((data.source || {}).current_claim || '—'))}
                ${row('Previous', escapeHtml((data.source || {}).previous_claim || '—'))}
            </div>
            <div class="j-ev-group"><h4>Outcome</h4>
                ${row('Assets analysed', s.assets_analysed || 0)}
                ${row('Affected', s.affected || 0)}
                ${row('Repaired', s.repaired || 0)}
                ${row('Requiring review', s.requiring_review || 0)}
                ${row('Operations avoided', s.operations_avoided || 0)}
                ${row('Verified opportunities', s.verified_opportunities || 0)}
                ${row('Storage verified', s.storage_verified ? 'yes' : '—')}
                ${row('Verification state', escapeHtml(s.verification_state || '—'))}
            </div>
            <details class="j-ev-details"><summary>Technical details (ChangeSet · repair plan · raw)</summary>
                <pre>${escapeHtml(JSON.stringify({ changeset: ev.changeset, repair_plan: ev.repair_plan, opportunities: ev.opportunities }, null, 2))}</pre>
            </details>`;
        $('evidenceModal').style.display = 'flex';
    }
    $('closeEvidence').addEventListener('click', () => { $('evidenceModal').style.display = 'none'; });

    // ---- shockwave / reverse wave (visualise real transitions) ----
    function triggerShockwave() {
        shockwaveLayer.innerHTML = '';
        for (let i = 0; i < 3; i++) {
            const ring = document.createElement('div');
            ring.className = 'shockwave-ring';
            ring.style.animationDelay = (i * 0.25) + 's';
            shockwaveLayer.appendChild(ring);
        }
        nodes.forEach((n, idx) => setTimeout(() => {
            n.el.style.transition = 'transform 0.35s cubic-bezier(0.34,1.56,0.64,1)';
            n.el.style.transform = 'translate(-50%,-50%) scale(1.15)';
            setTimeout(() => { n.el.style.transform = 'translate(-50%,-50%) scale(1)'; }, 400);
        }, idx * 80));
        setTimeout(() => { shockwaveLayer.innerHTML = ''; }, 3000);
    }
    function triggerReverseWave() {
        reverseWave.innerHTML = '';
        for (let i = 0; i < 2; i++) {
            const ring = document.createElement('div');
            ring.className = 'ring';
            ring.style.animationDelay = (i * 0.4) + 's';
            reverseWave.appendChild(ring);
        }
        setTimeout(() => { reverseWave.innerHTML = ''; }, 3500);
    }

    // ---- replay (visual only, NO backend mutation) ----
    async function replay() {
        if (replaying) return;
        replaying = true;
        triggerShockwave();
        // Re-illuminate nodes in impact order, then the timeline progressively.
        const order = [...nodes].sort((a, b) => b.intensity - a.intensity);
        order.forEach((n, i) => setTimeout(() => {
            n.el.style.transition = 'box-shadow .4s ease';
            n.el.classList.add('pulse');
            setTimeout(() => n.el.classList.remove('pulse'), 500);
        }, i * 180));
        for (let i = 0; i < (data.timeline || []).length; i++) {
            renderTimeline(i);
            await sleep(320);
        }
        renderTimeline();
        if (data.status === 'completed') triggerReverseWave();
        replaying = false;
    }

    // ---- full state refresh ----
    async function refreshState() {
        try {
            const res = await fetch(API);
            if (res.ok) data = await res.json();
        } catch (e) { return; }
        renderAssets(); renderTimeline(); renderMilestones(); renderProgressDots();
        updateInfo(); updateLiveStats(); updateTriumph(); renderOpportunities();
    }

    // ---- primary action dispatch ----
    function onPrimary() {
        const action = $('btnPrimary').dataset.action;
        if (action === 'repair') startRepair();
        else if (action === 'discover') discover();
        else if (action === 'review' || action === 'inspect') {
            const first = data.assets.find((a) => ['critical', 'affected', 'review'].includes(a.node_status));
            if (first) { selectAsset(first.id); openDrawer(first.id); }
        }
    }

    // ---- helpers ----
    function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
    function shorten(s) { return s.length > 42 ? s.slice(0, 20) + '…' + s.slice(-16) : s; }
    function prettyStatus(s) { return (s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) || '—'; }
    function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
    function elapsedSince(iso) {
        if (!iso) return '—';
        const then = new Date(iso).getTime();
        if (isNaN(then)) return '—';
        let s = Math.max(0, Math.floor((Date.now() - then) / 1000));
        const d = Math.floor(s / 86400); s -= d * 86400;
        const h = Math.floor(s / 3600); s -= h * 3600;
        const m = Math.floor(s / 60);
        if (d) return `${d}d ${h}h`;
        if (h) return `${h}h ${m}m`;
        return `${m}m`;
    }

    // ---- bind ----
    $('btnPrimary').addEventListener('click', onPrimary);
    $('btnReplay').addEventListener('click', replay);
    $('btnEvidence').addEventListener('click', openEvidence);
    $('btnEvidenceLink').addEventListener('click', openEvidence);
    $('btnTriumphEvidence').addEventListener('click', openEvidence);
    document.addEventListener('click', (e) => {
        if (!drawer.contains(e.target) && !e.target.closest('.asset-node')) {
            drawer.classList.remove('open');
            if (!selectedAssetId) depPathSvg.classList.remove('active');
        }
    });
    let resizeTimer;
    window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderAssets, 200); });

    // ---- init (renders the REAL current state immediately) ----
    createParticles();
    createOrbitalParticles();
    renderAssets();
    renderTimeline();
    renderMilestones();
    renderProgressDots();
    updateInfo();
    updateLiveStats();
    updateTriumph();
    renderOpportunities();
    setTimeout(triggerShockwave, 500);
})();
