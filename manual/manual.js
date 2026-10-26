// LlamaMXD User Manual — book chrome around vendor/flipbook-core.js (@gullabs/flipbook-core,
// a maintained fork of StPageFlip — see licenses/flipbook.txt), which owns the actual
// page-turning: corner dragging, the peel/curl, and the hard, single-page front/back covers
// (`hardCovers`). This file only wires up the surrounding controls (arrows, keyboard, the
// Contents page's jump links, the page counter) and the missing-screenshot fallback.
//
// Tuning the flip's own look: the settings object below (maxShadowOpacity, flippingTime, ...)
// and manual.css (the `.page-inner` rules — see "Leaf styling" below) are the two places that
// change — see https://github.com/gul-labs/flipbook#readme for the full settings list.
//
// vendor/flipbook-core.js is @gullabs/flipbook-core's own published build (dist/index.js),
// repackaged — the only edit is its trailing `export {...}` statement, replaced with a plain
// `window.Flipbook = {...}` assignment (see licenses/flipbook.txt). The package ships ESM/CJS
// only, and a `type="module"` script can't load from a `file://` page (Chromium refuses it —
// "Failed to load module script"), which is exactly how this manual is meant to be opened
// (double-click, no server). A classic global-namespace script has no such restriction.
(async function () {
    'use strict';

    const { PageFlip } = window.Flipbook;

    let singleMode = false; // set by the zoom logic; a single page has no second half
    const bookEl = document.getElementById('book');

    // ---- Text flowing from one page onto the next ----
    // A content page whose callouts don't fit is split automatically: the text is a stream of words,
    // the largest prefix that fits (measured once, on an off-screen copy at a reference page size) stays
    // on the page and the rest goes onto continuation pages inserted after it, each repeating only the
    // section name. Text scales with its page, so the split is the same at every zoom. Each section
    // (a divider up to the next blank / back cover) is then padded to an even page count, so the
    // next divider still lands on a right-hand page.
    const FLOW_PAGE_W = 660;        // the page width of the spread at its largest
    const FLOW_SLACK = 0.055;       // spare height: a different scale can re-wrap text onto one extra line (~0.05 of the page)

    function flowTokens(page) {
        const tokens = [];
        page.querySelectorAll('.callouts > .callout').forEach((callout, g) => {
            Array.from(callout.children).forEach((el, b) => {
                const tag = el.tagName.toLowerCase();
                const meta = { g, b, tag, cls: el.className };
                if (tag === 'h2') { tokens.push({ ...meta, text: el.innerHTML, heading: true }); return; }
                // A table or figure stays whole: it moves to the next page if it doesn't fit, never splits.
                if (tag === 'table' || tag === 'figure') { tokens.push({ ...meta, text: el.outerHTML, block: true }); return; }
                el.innerHTML.split(/(<br\s*\/?>)/i).forEach((part) => {
                    if (/^<br/i.test(part)) tokens.push({ ...meta, text: '<br>', br: true });
                    else part.split(/\s+(?![^<]*>)/).filter(Boolean).forEach((w) => tokens.push({ ...meta, text: w }));
                });
            });
        });
        return tokens;
    }

    function renderTokens(tokens, from, to) {
        let html = '', g = -1, b = -1, prevBr = true;
        // Closing tag of the element open before token `i` (a block token carries its own).
        const close = (i) => (tokens[i - 1].block ? '' : `</${tokens[i - 1].tag}>`);
        for (let i = from; i < to; i++) {
            const t = tokens[i];
            if (t.g !== g) {
                if (g !== -1) html += `${close(i)}</div>`;
                html += `<div class="callout">`;
                g = t.g; b = -1;
            }
            if (t.b !== b) {
                if (b !== -1) html += close(i);
                if (!t.block) html += `<${t.tag}${t.cls ? ` class="${t.cls}"` : ''}>`;
                b = t.b; prevBr = true;
            }
            html += t.block ? t.text : (t.br || prevBr ? '' : ' ') + t.text;
            prevBr = !!t.br;
        }
        if (g !== -1) html += `${close(to)}</div>`;
        return html;
    }

    function autoFlow() {
        const measurer = document.createElement('div');
        measurer.className = 'flow-measure';
        document.body.appendChild(measurer);
        const pageH = FLOW_PAGE_W * 540 / 448;

        // An empty callouts box the size the page leaves it, on an off-screen copy of the page.
        function measureBox(page) {
            measurer.textContent = '';
            const copy = page.cloneNode(true);
            copy.removeAttribute('data-id');
            copy.style.width = FLOW_PAGE_W + 'px';
            copy.style.height = pageH + 'px';
            copy.style.position = 'relative';
            const inner = document.createElement('div');
            inner.className = 'page-inner';
            while (copy.firstChild) inner.appendChild(copy.firstChild);
            copy.appendChild(inner);
            measurer.appendChild(copy);
            const box = copy.querySelector('.callouts');
            box.innerHTML = '';
            const room = box.clientHeight - FLOW_SLACK * pageH;
            box.style.flex = 'none';
            box.style.height = room + 'px';
            return box;
        }

        // The end (exclusive) of the longest run of tokens from `start` that fits the box.
        function fitEnd(box, tokens, start) {
            const n = tokens.length;
            const fits = (k) => {
                box.innerHTML = renderTokens(tokens, start, k);
                return box.scrollHeight <= box.clientHeight + 1;
            };
            if (fits(n)) return n;
            let lo = start, hi = n;
            while (lo < hi) {
                const mid = Math.ceil((lo + hi) / 2);
                if (fits(mid)) lo = mid; else hi = mid - 1;
            }
            return lo;
        }

        function makeContinuation(src, count) {
            const page = document.createElement('section');
            page.className = 'page content flow-continuation';
            page.dataset.id = `${src.dataset.id}-cont${count}`;
            const head = document.createElement('header');
            head.className = 'page-head';
            const crumb = src.querySelector('.page-head .crumb');
            if (crumb) head.appendChild(crumb.cloneNode(true));
            const callouts = document.createElement('div');
            callouts.className = 'callouts';
            page.append(head, callouts);
            return page;
        }

        Array.from(bookEl.querySelectorAll('.page.content')).forEach((src) => {
            const tokens = flowTokens(src);
            if (!tokens.length || fitEnd(measureBox(src), tokens, 0) >= tokens.length) return;
            let cur = src, start = 0, count = 0;
            for (;;) {
                let end = fitEnd(measureBox(cur), tokens, start);
                if (end < tokens.length) {
                    while (end > start && tokens[end - 1].heading) end--; // never strand a heading at the foot
                    if (end === start) end = start + 1;                    // always make progress
                }
                cur.querySelector('.callouts').innerHTML = renderTokens(tokens, start, end);
                if (end >= tokens.length) break;
                const next = makeContinuation(src, ++count);
                cur.after(next);
                cur = next;
                start = end;
            }
        });
        measurer.remove();

        // Keep every section an even number of pages long.
        bookEl.querySelectorAll('.page[data-id^="filler-"]').forEach((p) => p.remove());
        const pages = Array.from(bookEl.querySelectorAll('.page'));
        const isEnd = (p) => p.classList.contains('back-cover')
            || (p.classList.contains('blank') && /^blank-/.test(p.dataset.id || ''));
        pages.forEach((p, i) => {
            if (!p.classList.contains('divider')) return;
            let j = i + 1;
            while (j < pages.length && !isEnd(pages[j])) j++;
            if (j >= pages.length || (j - i - 1) % 2 === 0) return;
            const filler = document.createElement('section');
            filler.className = 'page blank';
            filler.dataset.id = `filler-${p.dataset.id}`;
            pages[j].before(filler);
        });
    }
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    autoFlow();

    const pageEls = Array.from(bookEl.querySelectorAll('.page'));
    const total = pageEls.length;

    const counter = document.getElementById('page-counter');
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const tocBtn = document.getElementById('toc-btn');
    const hint = document.getElementById('hint-toast');

    // ---- Page sides ----
    // The cover is index 0 and sits on the right, so every even index is a right-hand page and
    // every odd one a left-hand page. manual.css keys the rounded outer corners and the corner
    // section titles off these classes.
    pageEls.forEach((page, i) => page.classList.add(i % 2 === 0 ? 'side-right' : 'side-left'));

    // ---- Page numbers ----
    // The notices page and the Table of Contents are numbered i, ii, iii; the first section divider is
    // page 1 and counts on from there. Covers, blank leaves and dividers carry no number themselves.
    const ROMAN = ['', 'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'];
    const firstDivider = pageEls.findIndex((p) => p.classList.contains('divider'));
    const firstFront = pageEls.findIndex((p) => p.classList.contains('info'));
    pageEls.forEach((page, i) => {
        const front = /\b(info|toc)\b/.test(page.className);
        if (!front && !/\b(content|reference)\b/.test(page.className)) return;
        const num = document.createElement('div');
        num.className = 'page-num';
        num.textContent = front ? ROMAN[i - firstFront + 1] : String(i - firstDivider + 1);
        page.appendChild(num);
    });

    // ---- Leaf styling: give every page an inner wrapper the engine doesn't own ----
    // The engine draws position/size/clip-path and an opaque paper layer directly onto the leaf
    // root it adopts (`.stf__item` — our own `.page` element) so the fold is never see-through;
    // a `background` authored on that same root loses to the engine's own paper layer. Our actual
    // per-page colours (white content pages, yellow covers) move one level down, onto a plain
    // `.page-inner` div we wrap around each page's existing content before handing the elements to
    // `loadFromHTML` — untouched by the engine, so ordinary CSS on it just works. See manual.css's
    // `.page-inner` rules (and the flipbook README's "Styling" section) for the other half of this.
    pageEls.forEach((page) => {
        const inner = document.createElement('div');
        inner.className = 'page-inner';
        while (page.firstChild) inner.appendChild(page.firstChild);
        page.appendChild(inner);
    });

    const pageFlip = new PageFlip(bookEl, {
        width: 448,
        height: 540,
        sizing: 'responsive',
        minWidth: 260,
        maxWidth: 2400,
        minHeight: 314,
        maxHeight: 3200,
        usePortrait: true,
        maxShadowOpacity: 0.5,
        // The engine ties "shown alone, on its own side" to hard (rigid) density — there's no
        // setting for a solo-but-soft cover. Worth it: the same switch is what makes the engine's
        // fold opaque by construction (no more page bleeding through mid-turn, on any leaf).
        hardCovers: true,
        allowTouchScroll: false,
        flippingTime: 700,
        // We drive the pointer ourselves (see "Smoothed dragging" below), so the engine's own
        // default gesture handlers for every pointer kind never get attached.
        pointerInput: [],
    });

    function idOf(index) {
        return pageEls[index] ? pageEls[index].dataset.id : null;
    }
    function indexOf(id) {
        return pageEls.findIndex((p) => p.dataset.id === id);
    }

    const STORE_KEY = 'llamamxd-manual-page';

    function updateChrome() {
        const idx = pageFlip.getCurrentPageIndex();
        counter.textContent = `${idx + 1} / ${total}`;
        prevBtn.disabled = idx === 0;
        nextBtn.disabled = idx >= total - 1;
        persist(idx);
    }

    function persist(idx) {
        try { localStorage.setItem(STORE_KEY, String(idx)); } catch (e) { /* best-effort only */ }
    }

    function restoreSavedPage() {
        try {
            const saved = parseInt(localStorage.getItem(STORE_KEY), 10);
            if (Number.isInteger(saved) && saved > 0 && saved < total) pageFlip.turnToPage(saved);
        } catch (e) { /* file:// / private-mode storage can be unavailable; start at the cover */ }
    }

    // `flip` fires only for a real page change, never for the initial mount — `loaded` is what
    // carries the resolved page/count on first render (and on any later reload, which we never do).
    pageFlip.on('loaded', updateChrome);
    pageFlip.on('flip', updateChrome);

    pageFlip.loadFromHTML(pageEls);
    restoreSavedPage();



    // ---- Footer legibility ----
    // The Table of Contents button and the page counter are light text on the dark backdrop; once the
    // book or single page reaches them they turn black so they stay readable on the paper.
    const footerBits = [tocBtn, counter].filter(Boolean);
    function updateFooterTone() {
        footerBits.forEach((el) => {
            const r = el.getBoundingClientRect();
            const over = document.elementsFromPoint(r.left + r.width / 2, r.top + r.height / 2)
                .some((n) => n.classList && n.classList.contains('page'));
            el.classList.toggle('on-paper', over);
        });
    }
    window.addEventListener('resize', updateFooterTone);
    document.querySelector('.stage').addEventListener('scroll', updateFooterTone);
    setInterval(updateFooterTone, 250); // the page curl and fades move the paper without an event


    // ---- Zoom, and the fade into single-page view ----
    // The wheel zooms the whole book (up = in, down = out) by resizing it; the engine follows the
    // resize on its own. Zoomed out to the size the spread fits the window at, you see the whole
    // spread; zooming in past that fades to a single, larger page (no spine, so no rounded corners
    // and no curl), and zooming back out fades to the spread again.
    const shell = document.querySelector('.book-shell');
    const SPREAD_FIT_ZOOM = 1.02; // up to here the spread shows (1 = it fills the window); past it, one page
    const ZOOM_MIN = 0.4, ZOOM_MAX = 3, ZOOM_STEP = 1.1;
    const ZOOM_KEY = 'llamamxd-manual-zoom-v2';
    let zoom = 1;
    try {
        const saved = parseFloat(localStorage.getItem(ZOOM_KEY));
        if (saved >= ZOOM_MIN && saved <= ZOOM_MAX) zoom = saved;
    } catch (e) { /* storage unavailable: start at 1 */ }
    let appliedMode = null;
    let fadeTimer = null;
    let anchor = null;      // the pointer's screen position and where it sits on the book (0..1 each way)
    let pendingPage = null; // the page to land on after a spread <-> single switch
    let lightboxEl = null;  // the expanded screenshot overlay, while one is open

    function targetLayout() {
        const vw = window.innerWidth, vh = window.innerHeight;
        const single = zoom > SPREAD_FIT_ZOOM;
        const width = single
            ? Math.min(0.9 * vw, 0.74 * vh * 448 / 540) * zoom
            : Math.min(0.84 * vw, 1.55 * vh, 1320) * zoom;
        return { single, width };
    }
    function applyLayout(t, recentre) {
        shell.style.setProperty('--shell-w', t.width + 'px');
        shell.style.setProperty('--shell-ratio', t.single ? '448 / 540' : '896 / 540');
        document.body.classList.toggle('single-page', t.single);
        singleMode = t.single;
        // Portrait (single page) is chosen when the book's box is under twice minWidth.
        pageFlip.updateSettings({ usePortrait: t.single, minWidth: t.single ? Math.ceil(t.width) : 260 });
        pageFlip.update();
        if (pendingPage !== null) {
            pageFlip.turnToPage(pendingPage);
            pendingPage = null;
            updateChrome();
        }
        const stage = document.querySelector('.stage');
        // Scrollbars only while the book really is bigger than the window: the page curl briefly
        // paints outside the book, and with overflow always on that made scrollbars flicker in and out.
        const overflowing = t.width > window.innerWidth
            || t.width * (t.single ? 540 / 448 : 540 / 896) > window.innerHeight;
        stage.style.overflow = overflowing ? 'auto' : 'hidden';
        stage.classList.toggle('can-pan', overflowing && t.single);
        const r = shell.getBoundingClientRect();
        if (!overflowing) {
            // Nothing to scroll: drop any offset left over from an earlier zoom so margin:auto centres the book.
            stage.scrollLeft = 0;
            stage.scrollTop = 0;
        } else if (anchor && !recentre) {
            // Keep the spot under the pointer under the pointer, wherever the book grew or shrank.
            stage.scrollLeft += r.left + anchor.fx * r.width - anchor.x;
            stage.scrollTop += r.top + anchor.fy * r.height - anchor.y;
        } else {
            stage.scrollLeft = (stage.scrollWidth - stage.clientWidth) / 2;
            stage.scrollTop = (stage.scrollHeight - stage.clientHeight) / 2;
        }
        updateFooterTone();
    }
    // Which page is under a point of the spread, and where on that page it is.
    function spreadPageAt(fx) {
        const cur = pageFlip.getCurrentPageIndex();
        if (cur === 0 || cur === total - 1) return { page: cur, fx: fx < 0.5 ? fx * 2 : fx * 2 - 1 };
        const left = cur % 2 === 1 ? cur : cur - 1;
        const onRight = fx >= 0.5;
        return { page: Math.min(total - 1, left + (onRight ? 1 : 0)), fx: onRight ? fx * 2 - 1 : fx * 2 };
    }
    function relayout() {
        const t = targetLayout();
        if (appliedMode === null || t.single === appliedMode) {
            appliedMode = t.single;
            applyLayout(t);
            return;
        }
        // Mode switch: land on the page the pointer is over (spread -> single) and keep the
        // pointer on the same spot of it, or on the current page's half of the spread (single -> spread).
        if (anchor && t.single) {
            const hit = spreadPageAt(anchor.fx);
            pendingPage = hit.page;
            anchor.fx = hit.fx;
        } else if (anchor) {
            const cur = pageFlip.getCurrentPageIndex();
            const isRight = cur === 0 || cur % 2 === 0;
            anchor.fx = (isRight ? 0.5 : 0) + anchor.fx / 2;
        }
        appliedMode = t.single;
        shell.classList.add('fading');
        clearTimeout(fadeTimer);
        fadeTimer = setTimeout(() => {
            applyLayout(targetLayout(), true);
            shell.classList.remove('fading');
        }, 220);
    }
    window.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (lightboxEl || !e.deltaY) return;
        const next = zoom * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
        const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
        if (clamped === zoom) return;
        zoom = clamped;
        try { localStorage.setItem(ZOOM_KEY, String(zoom)); } catch (err) { /* best-effort */ }
        const r = shell.getBoundingClientRect();
        anchor = {
            x: e.clientX, y: e.clientY,
            fx: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
            fy: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
        };
        relayout();
    }, { passive: false });
    window.addEventListener('resize', () => { anchor = null; relayout(); });
    relayout();


    // ---- Navigation: page curl in the spread, a quick fade in single-page view ----
    // A single page has no spine to curl around, so it changes with a short fade instead.
    function goTo(index) {
        const target = Math.max(0, Math.min(total - 1, index));
        if (!singleMode) { pageFlip.flipToPage(target); return; }
        if (target === pageFlip.getCurrentPageIndex()) return;
        shell.classList.add('fading');
        clearTimeout(turnTimer);
        turnTimer = setTimeout(() => {
            pageFlip.turnToPage(target);
            updateChrome();
            shell.classList.remove('fading');
        }, 160);
    }
    function goStep(delta) {
        if (singleMode) goTo(pageFlip.getCurrentPageIndex() + delta);
        else if (delta > 0) pageFlip.flipNext();
        else pageFlip.flipPrev();
    }
    let turnTimer = null;

    prevBtn.addEventListener('click', () => { goStep(-1); dismissHint(); });
    nextBtn.addEventListener('click', () => { goStep(1); dismissHint(); });
    if (tocBtn) tocBtn.addEventListener('click', () => { goTo(indexOf('toc')); dismissHint(); });

    // ---- Smoothed dragging ----
    // The engine's own gesture handling (disabled above via pointerInput:[]) feeds the raw pointer
    // position straight into its fold calculation on every single mousemove, with no damping — any
    // small jitter near the corner-detection boundary shows up immediately as the fold
    // snapping/fighting over which way to go. We drive the same public API (startUserTouch/
    // userMove/userStop — documented "advanced" input plumbing for exactly this) ourselves, but
    // only ever push a position that's eased toward the real pointer (one exponential-smoothing
    // step per animation frame), so the fold settles into a steady chase instead of a twitchy snap.
    const DRAG_SMOOTHING = 0.12; // lower = smoother/laggier, higher = snappier; tune to taste

    // The engine's own hover-only corner peek (no button down — see userMove() in
    // vendor/flipbook-core.js) treats anywhere within diagonal/5 of a page's corner (~20% inset,
    // hardcoded, no public setting reaches it) as "on the corner", which is generous enough to
    // start peeling while the pointer is still over real content — e.g. the Contents list's own
    // links. We can't change the engine's own threshold, but since every pointer move already
    // routes through this file, we can shrink it ourselves: while the pointer isn't actually
    // gripping a page (no pointerdown yet), only forward its real position when it's within our
    // own, smaller zone; otherwise feed a point far off any corner so the engine's own "not on a
    // corner" path (showCorner's else branch) closes whatever peek was already showing. Once a real
    // drag starts inside that zone, the zone stops applying entirely — userMove keeps getting the
    // real position all the way across the page, same as before.
    const CORNER_ZONE_FRACTION = 0.09; // the engine's own trigger is ~0.2 (diagonal / 5)
    const FAR_FROM_ANY_CORNER = { x: -99999, y: -99999 };
    function nearOwnCorner(x, y) {
        const r = bookEl.getBoundingClientRect();
        const half = singleMode ? r.width : r.width / 2;
        const px = x >= half ? x - half : x; // position within its own page's half of the book
        const zone = Math.hypot(half, r.height) * CORNER_ZONE_FRACTION;
        return (px < zone || px > half - zone) && (y < zone || y > r.height - zone);
    }

    (function smoothedPointer() {
        let raw = null;
        let smoothed = null;
        let rafId = null;
        let touching = false;

        function bookPos(clientX, clientY) {
            const r = bookEl.getBoundingClientRect();
            return { x: clientX - r.left, y: clientY - r.top };
        }
        // Links, buttons and expandable screenshots take the click themselves; the engine would
        // otherwise read the press as a page turn.
        function isLinkOrButton(target) {
            const tag = target && target.tagName && target.tagName.toLowerCase();
            return tag === 'a' || tag === 'button'
                || !!(target.closest && target.closest('.cmp'))
                || !!(target.closest && target.closest('.screenshot:not(.missing):not(.artwork) img, figure.shot:not(.compare) img'));
        }
        function tick() {
            rafId = null;
            if (!raw) return;
            smoothed.x += (raw.x - smoothed.x) * DRAG_SMOOTHING;
            smoothed.y += (raw.y - smoothed.y) * DRAG_SMOOTHING;
            const onCorner = !singleMode && (touching || nearOwnCorner(smoothed.x, smoothed.y));
            pageFlip.userMove(onCorner ? smoothed : FAR_FROM_ANY_CORNER, false);
            if (Math.abs(raw.x - smoothed.x) > 0.4 || Math.abs(raw.y - smoothed.y) > 0.4) {
                rafId = requestAnimationFrame(tick);
            }
        }
        function schedule() {
            if (!rafId) rafId = requestAnimationFrame(tick);
        }

        bookEl.addEventListener('pointerdown', (e) => {
            if (singleMode || isLinkOrButton(e.target)) return;
            const pos = bookPos(e.clientX, e.clientY);
            raw = pos;
            smoothed = { x: pos.x, y: pos.y };
            touching = true;
            pageFlip.startUserTouch(pos);
        });
        window.addEventListener('pointermove', (e) => {
            raw = bookPos(e.clientX, e.clientY);
            if (!smoothed) smoothed = { x: raw.x, y: raw.y };
            schedule();
        });
        window.addEventListener('pointerup', (e) => {
            if (!touching) return;
            pageFlip.userStop(bookPos(e.clientX, e.clientY));
            raw = null;
            smoothed = null;
            touching = false;
        });
        bookEl.style.touchAction = 'none';
    })();

    document.querySelectorAll('[data-goto]').forEach((el) => {
        el.addEventListener('click', (e) => {
            e.preventDefault();
            const idx = indexOf(el.dataset.goto);
            if (idx >= 0) goTo(idx);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (lightboxEl) {
            if (e.key === 'Escape') closeLightbox();
            e.preventDefault();
            return;
        }
        const tag = document.activeElement && document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        switch (e.key) {
            case 'ArrowRight':
            case 'ArrowDown':
            case 'PageDown':
                goStep(1); dismissHint(); e.preventDefault(); break;
            case 'ArrowLeft':
            case 'ArrowUp':
            case 'PageUp':
                goStep(-1); dismissHint(); e.preventDefault(); break;
            case 'Home':
                goTo(0); dismissHint(); e.preventDefault(); break;
            case 'End':
                goTo(total - 1); dismissHint(); e.preventDefault(); break;
            default:
                break;
        }
    });

    // ---- Grab to pan ----
    // Once a single page outgrows the window, dragging with the left button scrolls the stage. Only
    // single-page view pans: in the spread the same drag is the page curl. A drag past PAN_THRESHOLD
    // swallows the click that follows it, so letting go over a screenshot doesn't expand it.
    const stageEl = document.querySelector('.stage');
    const PAN_THRESHOLD = 5;
    let pan = null;
    let swallowClick = false;
    stageEl.addEventListener('pointerdown', (e) => {
        if (e.button !== 0 || lightboxEl || !singleMode || !stageEl.classList.contains('can-pan')) return;
        if (e.target.closest('a, button, .cmp')) return;
        pan = { x: e.clientX, y: e.clientY, left: stageEl.scrollLeft, top: stageEl.scrollTop, moved: false };
    });
    window.addEventListener('pointermove', (e) => {
        if (!pan) return;
        const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
        if (!pan.moved) {
            if (Math.hypot(dx, dy) < PAN_THRESHOLD) return;
            pan.moved = true;
            document.body.classList.add('panning');
        }
        stageEl.scrollLeft = pan.left - dx;
        stageEl.scrollTop = pan.top - dy;
    });
    function endPan() {
        if (!pan) return;
        if (pan.moved) {
            swallowClick = true;
            setTimeout(() => { swallowClick = false; }, 0);
            document.body.classList.remove('panning');
        }
        pan = null;
    }
    window.addEventListener('pointerup', endPan);
    window.addEventListener('pointercancel', endPan);
    stageEl.addEventListener('dragstart', (e) => e.preventDefault());

    // ---- Click a screenshot to expand it ----
    // A full-window overlay shows the image at the largest size that fits; a click anywhere but on
    // the image, or Esc, closes it.
    function openLightbox(src, alt, compare) {
        if (lightboxEl) return;
        const overlay = document.createElement('div');
        overlay.className = 'lightbox';
        const img = document.createElement('img');
        if (compare) {
            overlay.appendChild(compare);
        } else {
            img.src = src;
            img.alt = alt || '';
            overlay.appendChild(img);
        }
        overlay.addEventListener('click', (e) => { if (e.target !== img && !e.target.closest('.cmp')) closeLightbox(); });
        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('open'));
        lightboxEl = overlay;
    }
    function closeLightbox() {
        const overlay = lightboxEl;
        if (!overlay) return;
        lightboxEl = null;
        overlay.classList.remove('open');
        setTimeout(() => overlay.remove(), 160);
    }
    // ---- Before/after comparison slider ----
    // Delegated, since the flow rebuilds page contents from markup. Dragging anywhere on the picture
    // moves the divider; a click without dragging expands a copy.
    let cmpDrag = null;
    let cmpStart = null;
    function setCmp(cmp, clientX) {
        const r = cmp.getBoundingClientRect();
        const pct = Math.min(100, Math.max(0, (clientX - r.left) / r.width * 100));
        cmp.style.setProperty('--pos', pct + '%');
    }
    document.addEventListener('pointerdown', (e) => {
        const cmp = e.target.closest && e.target.closest('.cmp');
        if (!cmp || e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        cmpDrag = cmp;
        cmp.classList.add('dragging');
        cmpStart = { x: e.clientX, y: e.clientY, moved: false };
        try { cmp.setPointerCapture(e.pointerId); } catch (err) { /* best-effort */ }
        setCmp(cmp, e.clientX);
    }, true);
    document.addEventListener('pointermove', (e) => {
        if (!cmpDrag) return;
        e.stopPropagation();
        if (Math.hypot(e.clientX - cmpStart.x, e.clientY - cmpStart.y) > 4) cmpStart.moved = true;
        setCmp(cmpDrag, e.clientX);
    }, true);
    // A press that never moved is a click: it expands the comparison (a copy, with its own slider).
    function endCmp(e) {
        const cmp = cmpDrag;
        cmpDrag = null;
        if (cmp) cmp.classList.remove('dragging');
        if (!cmp || e.type !== 'pointerup' || cmpStart.moved || cmp.closest('.lightbox')) return;
        openLightbox(null, null, cmp.cloneNode(true));
    }
    document.addEventListener('pointerup', endCmp, true);
    document.addEventListener('pointercancel', endCmp, true);

    document.addEventListener('click', (e) => {
        if (swallowClick) { e.stopPropagation(); return; }
        const img = e.target.closest && e.target.closest('.screenshot:not(.missing):not(.artwork) img, figure.shot:not(.compare) img');
        if (img) openLightbox(img.currentSrc || img.src, img.alt);
    }, true);

    // ---- Missing-screenshot fallback ----
    // A page image that hasn't been supplied yet degrades to a labelled placeholder instead
    // of a broken-image icon, so the manual still looks intentional while content is written.
    // A local 404 can resolve before this script (deliberately last in <body>) even runs, so
    // a fast connection can lose a plain 'error' listener attached only after the fact —
    // check the already-settled state first, then still listen for a slower failure.
    function watchMissing(img, onMissing) {
        if (img.complete && img.naturalWidth === 0) onMissing();
        else img.addEventListener('error', onMissing);
    }
    document.querySelectorAll('.screenshot img').forEach((img) => {
        watchMissing(img, () => img.closest('.screenshot').classList.add('missing'));
    });
    document.querySelectorAll('img.cover-mascot, img.llama-small').forEach((img) => {
        watchMissing(img, () => img.classList.add('missing'));
    });

    // ---- First-run hint ----
    let hintTimer = null;
    function dismissHint() {
        if (!hint) return;
        hint.classList.add('hidden');
        if (hintTimer) { clearTimeout(hintTimer); hintTimer = null; }
    }
    if (hint) {
        hintTimer = setTimeout(dismissHint, 5000);
        // changeState's payload is now an object ({ state }), not a bare string.
        pageFlip.on('changeState', (e) => {
            const state = e.data.state;
            if (state === 'user_fold' || state === 'flipping') dismissHint();
        });
    }
})();
