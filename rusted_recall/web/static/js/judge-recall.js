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
    let triumphCompactTimer = null;

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
        orbitalParticles.replaceChildren();
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
        orbit.replaceChildren();
        ghostLayer.replaceChildren();
        const positions = getPositions(data.assets.length);

        ghosts = data.assets.map((asset, i) => {
            const pos = positions[i];
            const el = document.createElement('div');
            el.className = 'asset-ghost';
            el.style.left = pos.x + 'px';
            el.style.top = pos.y + 'px';

            const preview = document.createElement('span');
            preview.className = 'preview';
            preview.textContent = asset.icon || '';

            const name = document.createElement('span');
            name.className = 'name';
            name.textContent = asset.name || '';

            const label = document.createElement('span');
            label.className = 'label';
            label.textContent = 'previous';

            el.append(preview, name, label);
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

            const ring = document.createElement('span');
            ring.className = `intensity-ring ${intensity > 0 ? 'active ' + ic : ''}`;

            const preview = document.createElement('span');
            preview.className = 'preview';
            preview.textContent = asset.icon || '';

            const name = document.createElement('span');
            name.className = 'name';
            name.textContent = asset.name || '';

            const statusTag = document.createElement('span');
            statusTag.className = 'status-tag';
            statusTag.textContent = (asset.classification || asset.node_status || '').toUpperCase();

            el.append(ring, preview, name, statusTag);
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
        if (coords.length < 2) {
            depPathSvg.classList.remove('active');
            depPathSvg.replaceChildren();
            return;
        }
        const fragment = document.createDocumentFragment();
        for (let i = 0; i < coords.length - 1; i++) {
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            line.setAttribute('x1', coords[i].x);
            line.setAttribute('y1', coords[i].y);
            line.setAttribute('x2', coords[i + 1].x);
            line.setAttribute('y2', coords[i + 1].y);
            if (i === coords.length - 2) {
                line.setAttribute('class', 'highlight');
            }
            fragment.appendChild(line);
        }
        depPathSvg.replaceChildren(fragment);
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
        // Evidence Count / Replay Count come straight from the persisted audit
        // log (directive: Impact Summary), so they survive refresh/reopen.
        if ($('statEvidence')) $('statEvidence').textContent = s.evidence_count != null ? s.evidence_count : 0;
        if ($('statReplays')) $('statReplays').textContent = s.replay_count != null ? s.replay_count : 0;
        // Impact = the engine's strongest persisted impact score (spec 13),
        // NOT an asset ratio and NOT the opportunity count. Stable across repair.
        updateGauge(s.impact_percent != null ? s.impact_percent : 0);
        const band = $('gaugeBand');
        if (band) band.textContent = s.impact_band && s.impact_band !== 'None' ? s.impact_band : '';
    }

    // ---- timeline ----
    function renderTimeline(activeIndex) {
        timelineEl.replaceChildren();
        (data.timeline || []).forEach((item, idx) => {
            const li = document.createElement('li');
            const isActive = activeIndex !== undefined ? idx === activeIndex : idx === data.timeline.length - 1;
            const isDone = activeIndex !== undefined ? idx < activeIndex : false;
            if (isActive) li.classList.add('active');
            if (isDone) li.classList.add('done');

            const dot = document.createElement('span');
            dot.className = 'event-dot';

            const time = document.createElement('span');
            time.className = 'time';
            time.textContent = item.time || '';

            const eventSpan = document.createElement('span');
            eventSpan.className = 'event';
            eventSpan.textContent = item.event || '';

            li.append(dot, time, eventSpan);
            if (item.detail) {
                const det = document.createElement('span');
                det.className = 'event-detail';
                det.textContent = item.detail;
                li.appendChild(det);
            }
            timelineEl.appendChild(li);
        });
    }

    function renderMilestones() {
        milestones.replaceChildren();
        const ms = [['Start', 0], ['Detect', 25], ['Analyze', 50], ['Repair', 75], ['Complete', 100]];
        ms.forEach(([label, pos]) => {
            const done = pos <= (STATUS_PROGRESS[data.status] || 0);
            const el = document.createElement('div');
            el.className = 'milestone' + (done ? ' active' : '');
            el.style.left = pos + '%';
            const tooltip = document.createElement('span');
            tooltip.className = 'tooltip';
            tooltip.textContent = label;
            el.appendChild(tooltip);
            milestones.appendChild(el);
        });
    }

    function renderProgressDots() {
        progressDots.replaceChildren();
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

        // recallName
        const nameEl = $('recallName');
        nameEl.replaceChildren();
        const nameText = document.createTextNode(src.name || 'Recall');
        const br = document.createElement('br');
        const subSpan = document.createElement('span');
        subSpan.className = 'sub';
        subSpan.textContent = src.current_claim || '';
        nameEl.append(nameText, br, subSpan);

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

        // currentOp
        const opEl = $('currentOp');
        opEl.replaceChildren();
        const opText = document.createTextNode(data.current_operation || '—');
        const blinkSpan = document.createElement('span');
        blinkSpan.className = 'cursor-blink';
        opEl.append(opText, blinkSpan);

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
        if (!verified) {
            if (triumphCompactTimer) {
                clearTimeout(triumphCompactTimer);
                triumphCompactTimer = null;
            }
            triumph.classList.remove('compact');
            triumph.style.display = 'none';
            orbitStage.classList.remove('breathing');
            return;
        }
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
        triumph.classList.remove('compact');
        orbitStage.classList.add('breathing');

        // Keep the cinematic completion moment, then collapse it into a
        // compact non-blocking banner so the real asset graph stays readable
        // and every node remains directly interactive.
        if (triumphCompactTimer) clearTimeout(triumphCompactTimer);
        triumphCompactTimer = setTimeout(() => {
            triumph.classList.add('compact');
            triumphCompactTimer = null;
        }, 1800);
    }

    // ---- opportunities ----
    function oppMetaRow(label, value) {
        const row = document.createElement('div');
        row.className = 'j-opp-meta';
        const k = document.createElement('span'); k.className = 'k'; k.textContent = label;
        const v = document.createElement('span'); v.className = 'v'; v.textContent = value;
        row.append(k, v);
        return row;
    }

    function renderDiscoverySummary(list) {
        // Truthful discovery outcome (spec 6/23): evaluated / verified / rejected
        // + rejection reasons, sourced from persisted audit evidence.
        const d = data.discovery;
        if (!d) return;
        const box = document.createElement('div');
        box.className = 'j-discovery';
        const head = document.createElement('div');
        head.className = 'j-discovery-head';
        head.textContent = `Discovery complete · ${d.evaluated} evaluated · ${d.verified} verified · ${d.rejected} rejected`;
        box.appendChild(head);
        (d.rejections || []).forEach((r) => {
            const row = document.createElement('div');
            row.className = 'j-opp-sub';
            row.textContent = `Rejected: ${r.asset || 'candidate'} — ${(r.reason || 'not eligible').replace(/_/g, ' ')}`;
            box.appendChild(row);
        });
        list.appendChild(box);
    }

    function renderOpportunities() {
        const list = $('oppList');
        list.replaceChildren();
        renderDiscoverySummary(list);
        const opps = (data.opportunities || []).filter((o) => o.status !== 'rejected');
        if (!opps.length) {
            const empty = document.createElement('div');
            empty.className = 'j-empty';
            empty.textContent = data.discovery
                ? 'No verified opportunities — every candidate was rejected with a recorded reason.'
                : 'No verified opportunities yet.' +
                  (data.status === 'completed' ? ' Use “Discover Verified Opportunities”.' : '');
            list.appendChild(empty);
            return;
        }
        opps.forEach((o) => {
            const div = document.createElement('div');
            div.className = 'j-opp';

            const title = document.createElement('div');
            title.className = 'j-opp-title';
            title.textContent = o.title || o.kind_label || o.kind || 'Opportunity';
            const statusSpan = document.createElement('span');
            statusSpan.className = 'j-opp-status ' + (o.status || '');
            statusSpan.textContent = o.status_label || o.status || '';
            title.appendChild(statusSpan);
            div.appendChild(title);

            if (o.rationale) {
                const rationale = document.createElement('div');
                rationale.className = 'j-opp-sub';
                rationale.textContent = o.rationale;
                div.appendChild(rationale);
            }

            if (o.kind_label) div.appendChild(oppMetaRow('Kind', o.kind_label));
            if (o.target_name) div.appendChild(oppMetaRow('Target', o.target_name));
            if (o.parent_name) div.appendChild(oppMetaRow('Repaired parent', o.parent_name));
            if (o.causal_path_names && o.causal_path_names.length) {
                div.appendChild(oppMetaRow('Causal path', o.causal_path_names.join(' → ')));
            }
            if (o.counterfactual) {
                div.appendChild(oppMetaRow('Counterfactual',
                    o.counterfactual.already_valid_before ? 'Was already valid' : 'Not valid before the change'));
            }
            if (o.feasibility_state) div.appendChild(oppMetaRow('Feasibility', o.feasibility_state));
            div.appendChild(oppMetaRow('Operations',
                `${o.native_operations || 0} native · ${o.generative_operations || 0} generative · ${o.blocked_operations || 0} blocked`));
            if (o.dedup_ref) div.appendChild(oppMetaRow('Ref', o.dedup_ref));

            if (o.executable) {
                const b = document.createElement('button');
                b.className = 'btn btn-success';
                b.textContent = 'Execute Opportunity';
                b.addEventListener('click', () => executeOpportunity(o.id, b));
                div.appendChild(b);
            } else if (o.result) {
                const r = document.createElement('div');
                r.className = 'j-opp-sub';
                const ok = (o.result.blocked || 0) === 0 && (o.result.executed || 0) === (o.result.total || 0);
                r.textContent = ok
                    ? `Executed: ${o.result.executed || 0}/${o.result.total || 0} operations, 0 blocked.`
                    : `Incomplete: ${o.result.executed || 0}/${o.result.total || 0} executed, ${o.result.blocked || 0} blocked.`;
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
        $('dClass').textContent = a.classification_label || a.classification || '—';
        $('dImpact').textContent = a.impact_percent != null
            ? `${a.impact_percent}%${a.impact_band && a.impact_band !== 'None' ? ' · ' + a.impact_band : ''}`
            : 'Not applicable';
        // Human-readable dependency chain, with the raw graph tokens available.
        const pathNames = (a.dependency_path_names && a.dependency_path_names.length)
            ? a.dependency_path_names : a.dependency_path;
        $('dPath').textContent = (pathNames && pathNames.length) ? pathNames.join(' → ') : 'No upstream dependency';
        $('dMethod').textContent = a.repair_method_label || a.derivation_method || a.repair_requirement || 'Not applicable';
        $('dStatus').textContent = a.job_status_label || 'No action required';
        $('dError').textContent = a.error_category || (a.job_status === 'completed' ? 'No error' : 'Not applicable');
        $('dB2').textContent = a.b2_key ? shorten(a.b2_key) : 'Not stored yet';
        $('dVersions').textContent = a.versions || 'No repaired version';
        $('dEvidence').textContent = a.sha256 ? a.sha256.slice(0, 12) + '…' : 'Not applicable';
        const cw = $('dCausalWrap');
        if (a.causal_reason) { cw.style.display = ''; $('dCausal').textContent = a.causal_reason; }
        else cw.style.display = 'none';
        // before/after: only a real repaired version is shown as "after"; other
        // states get an honest caption instead of a misleading image (spec 18).
        const pv = $('drawerPreview');
        const cap = $('previewCaption');
        if (a.preview_state === 'repaired' && (a.before_url || a.after_url)) {
            pv.style.display = 'flex';
            toggleImg($('dBefore'), a.before_url);
            toggleImg($('dAfter'), a.after_url);
            cap.style.display = 'none';
        } else {
            pv.style.display = 'none';
            const msg = {
                safe: 'No visual repair was required — this asset is verified safe.',
                pending_review: 'Awaiting a review decision — no repaired version exists yet.',
                pending_repair: 'Affected — repair not yet executed, so no repaired version exists.',
                none: 'No action required.',
            }[a.preview_state] || (a.before_url ? '' : 'No visual comparison available.');
            if (msg) { cap.style.display = ''; cap.textContent = msg; }
            else { cap.style.display = 'none'; }
        }
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
            if (!st.active) {
                clearInterval(pollTimer); pollTimer = null;
                if (data.status === 'completed') triggerReverseWave();
                // /status omits primary_action + opportunities; pull the full VM
                // once the engine settles so the footer action and the
                // opportunities panel reflect the new (post-repair) state.
                refreshState();
            }
        }, 1500);
    }

    // ---- opportunities discover/execute ----
    let discovering = false;
    async function discover() {
        if (discovering) return;  // prevent duplicate submission (spec 23)
        discovering = true;
        const btn = $('btnPrimary');
        const prevLabel = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = 'Discovering…'; }
        try {
            const res = await fetch(`${API}/opportunities/discover`, { method: 'POST' });
            const body = await res.json();
            data.opportunities = body.opportunities || [];
            data.discovery = body.discovery || data.discovery;
        } catch (e) { /* keep honest; refresh reflects reality */ }
        await refreshState();
        discovering = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Discovery complete';
        }
        void prevLabel;
    }
    async function executeOpportunity(id, btn) {
        if (btn) { if (btn.disabled) return; btn.disabled = true; btn.textContent = 'Executing…'; }
        try {
            const res = await fetch(`${API}/opportunities/${encodeURIComponent(id)}/execute`, { method: 'POST' });
            const body = await res.json();
            data.opportunities = body.opportunities || data.opportunities;
        } catch (e) { /* noop */ }
        await refreshState();
    }

    // ---- evidence modal ----
    let evidenceOpen = false;
    function closeEvidenceModal() {
        $('evidenceModal').style.display = 'none';
        evidenceOpen = false;
    }
    async function openEvidence() {
        if (evidenceOpen) return;  // single overlay only (spec 21)
        evidenceOpen = true;
        let ev;
        const body = $('evidenceBody');
        try {
            const res = await fetch(`${API}/evidence`);
            if (!res.ok) throw new Error('http ' + res.status);
            ev = await res.json();
        } catch (e) {
            body.replaceChildren();
            const err = document.createElement('div');
            err.className = 'j-empty';
            err.textContent = 'Could not load evidence. Please try again.';
            body.appendChild(err);
            $('evidenceModal').style.display = 'flex';
            return;
        }
        const s = ev.summary || {};
        body.replaceChildren();

        function createRow(key, value) {
            const row = document.createElement('div');
            row.className = 'row';
            const kSpan = document.createElement('span');
            kSpan.className = 'k';
            kSpan.textContent = key;
            const vSpan = document.createElement('span');
            vSpan.textContent = String(value);
            row.append(kSpan, vSpan);
            return row;
        }

        // Group 1: What changed
        const group1 = document.createElement('div');
        group1.className = 'j-ev-group';
        const h4_1 = document.createElement('h4');
        h4_1.textContent = 'What changed';
        group1.appendChild(h4_1);
        group1.appendChild(createRow('Source', (data.source || {}).name || '—'));
        group1.appendChild(createRow('New', (data.source || {}).current_claim || '—'));
        group1.appendChild(createRow('Previous', (data.source || {}).previous_claim || '—'));
        body.appendChild(group1);

        // Group 2: Outcome
        const group2 = document.createElement('div');
        group2.className = 'j-ev-group';
        const h4_2 = document.createElement('h4');
        h4_2.textContent = 'Outcome';
        group2.appendChild(h4_2);
        group2.appendChild(createRow('Assets analysed', s.assets_analysed || 0));
        group2.appendChild(createRow('Affected', s.affected || 0));
        group2.appendChild(createRow('Repaired', s.repaired || 0));
        group2.appendChild(createRow('Requiring review', s.requiring_review || 0));
        group2.appendChild(createRow('Operations avoided', s.operations_avoided || 0));
        group2.appendChild(createRow('Verified opportunities', s.verified_opportunities || 0));
        group2.appendChild(createRow('Storage verified', s.storage_verified ? 'yes' : '—'));
        group2.appendChild(createRow('Verification state', s.verification_state || '—'));
        body.appendChild(group2);

        // Details: technical details
        const details = document.createElement('details');
        details.className = 'j-ev-details';
        const summary = document.createElement('summary');
        summary.textContent = 'Technical details (ChangeSet · repair plan · raw)';
        details.appendChild(summary);
        const pre = document.createElement('pre');
        const jsonStr = JSON.stringify({
            changeset: ev.changeset,
            repair_plan: ev.repair_plan,
            opportunities: ev.opportunities
        }, null, 2);
        pre.textContent = jsonStr;
        details.appendChild(pre);
        body.appendChild(details);

        $('evidenceModal').style.display = 'flex';
    }
    $('closeEvidence').addEventListener('click', closeEvidenceModal);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && evidenceOpen) closeEvidenceModal(); });

    // ---- shockwave / reverse wave (visualise real transitions) ----
    function triggerShockwave() {
        shockwaveLayer.replaceChildren();
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
        setTimeout(() => { shockwaveLayer.replaceChildren(); }, 3000);
    }
    function triggerReverseWave() {
        reverseWave.replaceChildren();
        for (let i = 0; i < 2; i++) {
            const ring = document.createElement('div');
            ring.className = 'ring';
            ring.style.animationDelay = (i * 0.4) + 's';
            reverseWave.appendChild(ring);
        }
        setTimeout(() => { reverseWave.replaceChildren(); }, 3500);
    }

    // ---- replay (visual only, NO backend mutation) ----
    async function replay() {
        if (replaying) return;  // no parallel replay (spec 22)
        replaying = true;
        const rbtn = $('btnReplay');
        const rlabel = rbtn ? rbtn.textContent : '';
        if (rbtn) { rbtn.disabled = true; rbtn.textContent = 'Replaying…'; }
        // Record the replay in the audit log (visual-only: no repair/discovery/
        // execute) so Replay Count is real and survives refresh/reopen.
        try {
            const res = await fetch(`${API}/replay`, { method: 'POST' });
            if (res.ok) { const b = await res.json(); if (b.summary) { data.summary = b.summary; updateLiveStats(); } }
        } catch (e) { /* keep honest; a later refresh reflects reality */ }
        triggerShockwave();
        // Re-illuminate nodes in impact order, then the timeline progressively.
        // Uses ONLY recorded state — no repair/discovery/execute is triggered.
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
        if (rbtn) { rbtn.disabled = false; rbtn.textContent = rlabel || 'Replay'; }
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