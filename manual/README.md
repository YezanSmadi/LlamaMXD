# manual/

The user-facing manual: `manual.html`, opened directly (double-click, or Settings &rsaquo; About &rsaquo;
User Manual) — no server, no build step. `manual.css` is the visual design; `manual.js` wires up the
book chrome (arrows, keyboard, the Contents page's jump links) around `vendor/flipbook-core.js`
(`@gullabs/flipbook-core`, MPL-2.0, a maintained fork of StPageFlip — see `licenses/flipbook.txt`),
which owns the actual page-turning. Adding, removing or reordering a page needs no changes to either
file.

**Tuning the flip's look** — `maxShadowOpacity`, `flippingTime`, `hardCovers` and the rest of the
engine's settings are in the `new PageFlip(...)` call near the top of `manual.js`; per-page colour and
layout is `manual.css`'s `.page-inner` rules (see the comment at the top of `manual.js` for why it's
`.page-inner` and not `.page` itself). See https://github.com/gul-labs/flipbook#readme for the full
settings list.

`vendor/flipbook-core.js` is that package's own published build, repackaged: the package ships ESM/CJS
only, and a `type="module"` script can't load from a `file://` page in Chromium (the exact way this
manual is meant to be opened) — so the one change is its trailing `export {...}` swapped for a plain
`window.Flipbook = {...}` assignment. See `licenses/flipbook.txt` for the full explanation and the
MPL-2.0 text.

## Adding a screenshot

Each content page's `<img>` names the file it wants, e.g. `images/muxing-video.png`. Drop a PNG of that
name into `manual/images/` and it appears in place of the placeholder on next reload. Nothing needs
registering — a missing image just falls back to a labelled placeholder box instead of a broken-image
icon, so the manual still looks intentional while you're filling it in.

**Pictures inside the text** (a popup, a before/after) are a `<figure class="shot">` with an `<img>`
(give it the file's `width` / `height` so its space is reserved before it loads) and a `<figcaption>`,
placed in a `.callout` after the paragraph it illustrates; `class="shot pair"` with two
`<span class="half">` children puts two side by side. A figure is kept whole like a table: when it doesn't
fit under the text it moves to the next page. Clicking one zooms it, like the main screenshots.

**Before/after slider.** `<figure class="shot compare">` holds a `.cmp` box with two same-sized images
(`.cmp-a` underneath, `.cmp-b` clipped from the divider rightwards), two `.cmp-tag` labels, and a `.cmp-handle`; see the Encoding / Video page. Dragging anywhere on it moves the divider (it
is handled by delegated listeners in `manual.js`, so it survives the page flow re-rendering, and it does not
turn the page); a click without dragging opens a copy in the zoom overlay, which has its own working slider.

## Adding, removing or reordering a page

Every page is one `<section class="page ...">` in `manual.html`, in reading order — that order *is* the
book's order. `manual.js` pairs them up into spreads two at a time (`[1,2]`, `[3,4]`, ...), with the very
first page (the cover) and the very last page (the back cover) always shown alone. To add a page, copy the
nearest matching block (`content`, `reference`, or `toc`/`cover`/`back-cover` for the special ones)
and give it a unique `data-id`. To remove one, delete its block. To reorder, move the block. Then add (or
remove) its entry in the Table of Contents page (`data-id="toc"`) — `<a data-goto="...">` where the value
matches the target page's `data-id`.

**Keep the total page count even.** The pairing only leaves the *last* page alone (as the back cover) when
an even number of pages sit behind the cover — with an odd number, the back cover would end up paired with
the page before it instead of standing alone. The book is 72 pages today; if you add or remove a page and the
count goes odd, add or remove a page somewhere in the middle to balance it back out.

**Front matter and section dividers.** After the cover come a blank left page and the notices page
(`info`), then the two Contents pages. Every section opens with a spread: a `blank` left page (odd index,
even page number) and a `divider` right page holding the centred section title. A section with an odd
number of pages ends on a left page, so it is followed by one blank `filler-*` page to put the next
divider's blank leaf back on the left; Reference (6 pages) and Troubleshooting & FAQ (6) need none. Downloading and Queuing are each
one page, so each ends on a filler.
Blank, divider and notices pages carry no page number.

**Page sides.** A page's index decides its side (even = right-hand, odd = left-hand, the cover being
index 0), and `manual.js` tags it `side-left` / `side-right`. That drives the rounded outer corners and
puts each page's section title (`.crumb`) in its outer top corner, so inserting a page shifts the pages
after it to the other side automatically.

**No scrollbars, anywhere.** Text that is too long for its page flows onto an automatically inserted
continuation page (`autoFlow` in `manual.js`), never into a scrolling box: `.callouts` is `overflow: hidden`,
and `FLOW_SLACK` keeps a spare line free so a different zoom that re-wraps text can't clip it. Write long
text in the `.callouts` as usual and let it split; don't add `overflow: auto` / `scroll` to anything in the book.
Continuation pages change the page count, so keep it even (see above).

## Previewing while you work

Opening `manual.html` straight from disk (`file://`) works. It's also fine to serve the repo root and
browse to `/manual/manual.html`, which is what `.claude/launch.json`'s `manual-preview` config does
(Claude Code's Browser pane picks it up automatically); by hand, `python -m http.server` from the repo
root, then open `http://localhost:8000/manual/manual.html`.
