# EyesOnGuj Frontend Pass - Implementation Plan

This replaces the earlier draft plan. Same goal (rebrand Sentinel to
EyesOnGuj, unify the visual system, add light/dark themes, add a custom
SVG/icon system, keep the map as the hero, change nothing about backend
behavior) but grounded in what is actually in this repo right now, not
generic best practice. Every section below references real files, real
class names, and real gaps found while auditing all three models. Where
the earlier draft said "the exact values are left to implementation,"
this version gives the implementer a concrete starting point instead.

This is a plan and checklist, not a spec to follow line by line. Use
judgment. The checklist at the end is organized by finished work, not by
day or week - check items off as they're actually done.

---

## 1. What's already there (read this before touching anything)

The earlier plan assumed a blank-ish slate. It isn't one. Skipping this
section is the most likely way to waste time redoing work that already
exists or breaking something that already works.

- **There is already a real design-token system.** `model1-registry/app/static/css/main.css`
  (1,300 lines, one file, no build step) opens with a `:root` block
  defining `--bg-primary`, `--bg-secondary`, `--bg-card`, `--bg-glass`,
  `--text-primary/secondary/muted`, `--accent` + `--accent-light` +
  `--accent-glow`, `--success/danger/warning` (each with a matching
  `-bg` tint), border/radius/shadow/transition scales, and layout
  constants (`--nav-height`, `--sidebar-width`). There are also working
  `.badge`, `.badge-dot`, and `.btn` (`--primary`/`--secondary`/`--danger`/`--sm`/`--icon`)
  component classes already built on these tokens. This is a genuine
  head start - the job is to extend this system (add light-mode values,
  rebrand the palette) and get every page actually using it, not build
  a parallel one from scratch.
- **It is dark-mode-only today, and not in a way that's ready to branch.**
  Every color in `:root` is a fixed hex/rgba value; there is no
  `data-theme` attribute, no `prefers-color-scheme` media query, and no
  light equivalents defined anywhere. Light mode is a real, from-scratch
  addition, not a toggle waiting to be wired up.
- **There is a working precedent for persisted UI state to copy.**
  `base.html`'s sidebar-collapse state is stored in
  `localStorage.getItem('sentinel_sidebar_collapsed')` and applied via
  an Alpine `x-data` block on `<html>` before the body renders. Theme
  persistence should use the same mechanism (a same-page, no-flash
  localStorage read on `<html>`, not a cookie or a server round-trip) -
  it's already proven to work in this codebase. (Small naming note: that
  key itself still says `sentinel_` - see the branding section.)
- **The real camera states are exactly three, fixed at the database
  level:** `online`, `offline`, `maintenance` - a Postgres `CHECK`
  constraint on `cameras.connectivity_status`
  (`docs/model1/README.md` section 2), not just a UI convention. Use
  these three names throughout, not the draft plan's looser "Live /
  Online, Maintenance, Offline / Unavailable" phrasing - "online" is
  the actual value that flows through the API and templates.
- **Status/badge styling is already fragmented across at least nine
  independent naming schemes**, each invented per page as it was built:
  `badge` / `badge-dot` (shared, in `main.css`), plus page-local
  `status-pill`, `badge-tag`, `badge-v`, `cam-badge`, `ec-badge`,
  `plate-badge`, `sys-badge`, `sys-status-pill` (found in `federation.html`,
  `detection.html`, `live.html`, `persons_watchlist.html`, `watchlist.html`).
  This is the single most concrete symptom of "feels like independently
  developed pages," and it's exactly what section 8 (Shared Components)
  below is for.
- **Ten templates carry their own large embedded `<style>` block**
  instead of extending `main.css`, which is exactly how the badge
  fragmentation above happened - each page's author had nowhere shared
  to put a new style, so they added a local one:

  | Template | Embedded `<style>` |
  |---|---|
  | `federation.html` | ~942 lines |
  | `recorded_detection.html` | ~881 lines |
  | `detection.html` | ~818 lines |
  | `live.html` | ~765 lines |
  | `persons_watchlist.html` | ~621 lines |
  | `watchlist.html` | ~550 lines |
  | `face_detection.html` | ~558 lines |
  | `alerts.html` | ~231 lines |
  | `anpr.html` | ~221 lines |
  | `cameras_list.html` | ~201 lines |

  That's roughly 6,000 lines of page-local CSS outside `main.css`. Not
  all of it needs to move - genuinely page-specific layout can stay
  local - but any color, spacing, radius, shadow, or status treatment
  duplicated from (or drifted from) the shared tokens should move into
  `main.css` or a small set of shared partials as each page is touched.
  `alerts.html` is a clean, small example of the problem worth doing
  first: it hardcodes its own severity colors (`#f87171` for critical,
  etc.) in a local `<style>` block instead of using the `--danger` /
  `--warning` tokens that already exist in `main.css`.
- **There is no favicon and no logo asset of any kind in the repo
  today.** Not "outdated," genuinely absent - no `.ico`, no logo image,
  no `<link rel="icon">` anywhere in `base.html` or any other template.
  Section 3 below is a from-scratch addition, not a swap.
- **Branding cleanup has an exact, closed list - 21 occurrences of
  "Sentinel" across 18 files**, all of them page `<title>` blocks, the
  nav brand text, the meta description, the login page heading, and two
  source comments. There is nothing hidden here; grep found all of it
  and it's listed in section 3.
- **The real navigation is a collapsible sidebar with three sections**
  already, not a hypothetical structure to invent: "Registry & GIS"
  (Map Dashboard, Live Feeds, Cameras, Departments, Districts, Audit
  Log, Gap Analysis), "AI & Analytics" (Detections, Recorded AI,
  Vehicles, Person Watchlist, Face Detection, ANPR, Alerts Feed), and
  "Federation" (VMS Federation). Every link already uses an emoji as
  its icon (shield for the brand mark, then one emoji per nav item).
  Section 4 and section 5 below map directly onto this existing
  structure rather than replacing it.
- **External assets already load from CDNs with no build step**: Google
  Fonts (Inter, weights 300-800), Leaflet 1.9.4 + Leaflet.markercluster
  1.5.3 (unpkg), HTMX 1.9.12, Alpine.js 3.14.3. Keep this pattern for
  anything new - do not introduce a bundler or a frontend framework for
  this pass (matches the original plan's intent, and matches
  `docs/model1/README.md`'s own stated reason for not using React: the
  camera/status data is shared, server-owned state, and HTMX's
  render-from-the-database-every-time model is a deliberate choice, not
  an oversight to correct).

## 2. Known backend-shaped gaps that touch this work

These came out of the Model 1/2/3 backend audits (see
`Model1_Final_Report.md`, `Model2_Final_Report.md`,
`Model3_Final_Report.md`). None of them require a backend rewrite, but
each one intersects with a page this plan touches, so flagging them
here so they aren't mistaken for frontend bugs, and so a fix can ride
along cheaply if you're already in that file:

- **`cameras_list.html` / `cameras_table_partial.html`**: the backend
  route these HTMX-swap into (`GET /cameras/table`) has no login check,
  unlike every sibling page route. Not a template problem - the
  template is doing exactly what it should with what it's given - but
  worth a one-line backend fix while this area is open for the registry
  redesign (section 9).
- **`recorded_detection.html`**: this page already renders a `Plate:`
  field and a plate column expecting `d.detected_plate`. That field
  will keep showing the empty-value fallback for every row until the
  backend's uploaded-video path is wired to a real ANPR provider
  (currently it never attempts plate recognition at all, regardless of
  config - see `Model2_Final_Report.md` section 2). Restyling this
  field is in scope for this pass; making it show real data is not -
  don't spend polish time trying to make an always-empty field "look
  more populated," and don't treat the dash as a frontend bug to chase.
- **`face_detection.html`**'s WebSocket connection
  (`/api/v1/face-detection/ws/{job_id}`) currently has no server-side
  auth check at all, unlike the other two WebSocket endpoints in the
  app. The frontend code is already written correctly (same-origin
  `new WebSocket(...)`, relying on the cookie, exactly like the other
  two) - this is purely a backend fix, nothing to change here, just
  don't be surprised if it comes up during testing.
- **`federation.html`** never calls the already-built, already-tested
  `GET /api/v3/alerts` or `POST /api/v3/alerts/{id}/acknowledge`
  endpoints. Alerts only ever appear as transient WebSocket toasts with
  no persistent list and no acknowledge action. This one actually is
  frontend work, and it's folded into section 12 below as a real
  checklist item, not just a note - the backend is done and tested, so
  this is a good candidate for early, high-value work: adapt the list +
  acknowledge pattern that already exists and works in `alerts.html`
  rather than designing a new one.

## 3. EyesOnGuj branding - the exact list

Every visible occurrence of the old name, found by direct search, not
estimated:

| File | What to change |
|---|---|
| `base.html` | `<title>` default block, `<meta name="description">`, `nav-title` span text, and the `localStorage` key `sentinel_sidebar_collapsed` (rename for consistency; the old key will just start empty for existing sessions, harmless) |
| `login.html` | `<title>` block, the `Sentinel Command Portal` heading |
| `map.html`, `cameras_list.html`, `departments_list.html`, `districts_list.html`, `audit.html`, `gap_analysis.html`, `live.html`, `detection.html`, `recorded_detection.html`, `watchlist.html`, `persons_watchlist.html`, `face_detection.html`, `anpr.html`, `alerts.html`, `federation.html`, `placeholder.html` | Each one's `<title>` block |
| `static/css/main.css` | Header comment line 2 |
| `static/js/map.js` | Header comment line 2 |
| `live.html` | A second source-comment reference around line 261 |

Nothing else references the old name anywhere in `templates/` or
`static/`. When this list is done, a repo-wide `grep -ri sentinel
model1-registry/app/templates model1-registry/app/static` should return
nothing but incidental matches (there are none currently, but re-check
after edits) - use that grep as the literal definition-of-done for the
branding section, not a subjective "looks rebranded" judgment call.

Do not rename anything in Python code, the database, environment
variables, or the product's internal identifiers ("Sentinel" as an
internal/backend name is out of scope - this is a user-facing
presentation change only, per the preserve-the-backend principle in
section 13).

## 4. Logo and favicon

Starting from nothing (section 1), so there's no existing mark to
preserve continuity with. The nav brand currently pairs a shield emoji
with the wordmark at 3 sizes of meaning (full brand, nav-collapsed icon,
browser tab) - that's a reasonable structure to keep:

- A full lockup (mark + "EyesOnGuj" wordmark + the existing "Registry &
  GIS" style subtitle) for the expanded sidebar/nav-brand and the login
  page.
- A compact mark-only version for the collapsed sidebar state
  (`sidebarCollapsed` already exists as an Alpine state - the current
  emoji-only nav-brand in that state is what the mark replaces).
- A small, simplified version for the favicon (works down to 16x16 -
  simplify hard, don't just shrink the full mark).

Concept: something evoking an eye/lens (camera + oversight) combined
with a simple geographic marker or outline suggestive of Gujarat, in the
existing accent color family (`--accent` / `--accent-light`) so it reads
as belonging to the app immediately. Keep it to one or two colors so it
still works as a single-color favicon and in both themes. Build it as
inline SVG (or an `.svg` file referenced by `<img>`/`<use>`), not a
raster export, so it stays crisp at every size mentioned above and can
be recolored per-theme with CSS if needed.

Add the actual `<link rel="icon">` (there is currently none at all) and
an `apple-touch-icon` to `base.html`'s `<head>`.

## 5. Design tokens: extend `main.css`, don't replace it

Keep every existing variable name in `:root` (`--bg-primary`,
`--text-secondary`, `--success`, `--radius-md`, etc.) so nothing that
already references them breaks. Do this:

1. **Rebrand the palette values**, not the variable names - pick the
   actual EyesOnGuj accent/success/warning/danger hex values and swap
   them in. Every place already using `var(--accent)`, `var(--success)`,
   etc. picks up the change automatically.
2. **Add a light-theme block**, gated on a `data-theme` attribute on
   `<html>` (e.g. `:root[data-theme="light"] { --bg-primary: ...; }`),
   sitting alongside the existing dark values rather than replacing
   them. Dark stays the default (`:root` with no attribute, or
   `data-theme="dark"` explicitly) so nothing regresses if the
   attribute is ever missing.
3. **Fill in the token gaps the current system doesn't have yet but
   this pass needs**: a `--surface-elevated` step distinct from
   `--bg-card` (for popups/modals/dropdowns sitting above a card), a
   `--focus-ring` token (there's no visible focus treatment defined
   anywhere today - a real accessibility gap, not just a style
   preference), and explicit `--info` / `--info-bg` tokens to sit
   alongside the existing success/warning/danger trio (currently only
   `badge--info` exists as a class with no dedicated token backing it -
   check `main.css` around line 630).
4. **Migrate the hardcoded per-page colors that duplicate these tokens**
   as each page is touched (the `alerts.html` severity-color example
   from section 1 is the clearest case, but check each page's embedded
   `<style>` block for the same pattern before assuming it's
   page-specific).

## 6. Theme switching

- One control in the nav (`nav-user` area in `base.html`, next to the
  existing user badge/logout button) cycling Light / Dark / System, or
  at minimum Light / Dark if System adds complexity not worth it here.
- Persist via `localStorage` (see section 1's existing precedent) under
  a new, correctly-named key (e.g. `eyesonguj_theme`), read and applied
  in the same `x-data` block on `<html>` in `base.html` that already
  handles `sidebarCollapsed`, before first paint, to avoid a
  flash-of-wrong-theme on load.
- Apply the theme as the `data-theme` attribute described in section 5.
- Test explicitly: HTMX table swaps (`cameras_table_partial.html`
  reloading into `#cameras-tbody`), the camera-form modal opening
  mid-session, and a WebSocket-driven page (`live.html`, `detection.html`,
  `federation.html`) receiving pushed content - all of these inject
  markup after the initial page load, and it's easy for injected markup
  to end up unstyled or using stale colors if it was written assuming
  only the dark palette existed.

## 7. Custom SVG / icon system

Every nav-sidebar link, and the nav brand mark, currently uses a raw
emoji as its icon (shield, map, TV, camera, government building, pin,
scroll, bar chart, magnifying glass, video cassette, car, person,
target, car again, siren, and link, in that order down the sidebar).
That's the literal, complete replacement list for the primary icon set
- there's no ambiguity here about what needs an icon, it's exactly
these positions in `base.html`.

Priority order (matches section 1's existing state, so the highest-value
work happens first):

1. **Camera state indicators** (online / offline / maintenance) - the
   plan's own stated baseline requirement, and the one place a
   consistent visual pays off immediately across the most surface area:
   the map markers (`static/js/map.js`'s `statusEmoji` lookup and the
   `L.divIcon` HTML it builds), the `.badge-dot` classes in `main.css`,
   and every `badge--online` / `badge--offline` / `badge--maintenance`
   usage across `cameras_table_partial.html`, `camera_form.html`, and
   the map popups. Build these as one small SVG set (or one sprite)
   with three consistent state treatments, then point every one of
   those existing call sites at it instead of the current emoji/colored-dot
   mix. Never rely on color alone - each marker/badge keeps a visible
   text label alongside the icon, matching the plan's own accessibility
   requirement in section 30 of the original draft.
2. **Sidebar navigation icons** - replace the emoji list above with a
   consistent SVG icon set (a single stroke-width, single style
   family - outline or filled, pick one and keep every icon in that
   family consistent). This is the highest-visibility, lowest-risk
   place to establish the visual language, since it's one file
   (`base.html`) touched once.
3. **The brand mark itself** (section 4).
4. Everything else only as it comes up naturally while working through
   sections 9-12 (an alerts/severity glyph while touching `alerts.html`,
   a detection/target glyph while touching `detection.html`, and so
   on) - don't front-load a large icon library before there's a page
   that needs each one.

Organize as inline `<svg>` partials included via Jinja
(`{% include %}`) or a small `icons.html` macro file, whichever reads
more naturally next to how `base.html` already structures the sidebar
- either is fine, the requirement is one consistent place to find and
update an icon, not a specific folder layout.

## 8. Shared components - the highest-leverage work in this whole plan

Given section 1's finding of nine independent badge/status naming
schemes and ~6,000 lines of page-local CSS, this section is where most
of the "feels like one product" outcome actually comes from - more than
any individual page's redesign.

- **Status badge**: one component, one set of classes, replacing
  `badge`/`badge-dot` (keep these two, they're already shared and
  correctly token-based) and retiring `status-pill`, `badge-tag`,
  `badge-v`, `cam-badge`, `ec-badge`, `plate-badge`, `sys-badge`,
  `sys-status-pill` in favor of it. This covers camera connectivity
  status, alert severity (Model 2's `critical`/`high`/`medium`
  categories and Model 3's federation alert severities alike), and
  federation system status (`connected`/`disconnected`/`unknown`) as
  one visual family with different color mappings, not different
  component families.
- **Buttons**: `.btn`/`.btn--primary`/`.btn--secondary`/`.btn--danger`/`.btn--sm`/`.btn--icon`
  already exist in `main.css` and are already used in several
  templates (`base.html`'s logout button, `camera_form.html`'s modal
  actions) - audit the pages with embedded `<style>` blocks for
  one-off button styles that duplicate these and consolidate.
- **Cards/panels**: define the shared treatment once (radius, border,
  background, padding, heading style) using the existing
  `--radius-md`/`--shadow-md`/`--bg-card` tokens, then apply it to the
  map's control cards, the analytics pages' result cards, and the
  federation topology cards, which currently each define their own
  card look inside their own `<style>` block.
- **Tables**: `cameras_table_partial.html` is the reference
  implementation to generalize from (it's already HTMX-swapped and
  reasonably clean) - apply the same header/row/hover/badge conventions
  to the audit log table (`audit.html`) and any tabular sections inside
  the analytics pages.
- **Empty/loading/error states**: currently inconsistent to nonexistent
  per page - define one small partial/macro for "no results" (with the
  clear-filters pattern from the original draft) and one for a loading
  skeleton/spinner, then use them everywhere a table or list can be
  empty (cameras table, audit log, alerts list, federation events feed,
  watchlist tables).

Building these as a small number of shared Jinja partials/macros (not
one per page) is what actually prevents the badge-class sprawl from
recurring the next time someone adds a page.

## 9. The map page (`map.html` + `map.js`) - the hero, treat it that way

Current state is already functional and reasonably good: Leaflet +
OSM base layer, marker clustering, district-boundary GeoJSON overlay,
department/district/status filters, a gap-analysis overlay toggle, and
popups built directly in `map.js` (the `renderMarkers()` function,
roughly lines 240-340). This section is refinement, not a rebuild:

- Re-skin the existing `.map-control-card` panels (district filter,
  department checkboxes, spatial-overlay toggles) and the
  `.map-stat-pill` bottom bar with the shared card/badge components
  from section 8, instead of their current bespoke styling.
- Replace the marker icon logic (`statusEmoji` lookup + inline
  `L.divIcon` HTML string in `map.js`) with the new camera-state SVG
  set from section 7. Keep the exact same data-driven logic (status
  drives the icon), just swap what gets rendered.
- Rebuild the popup HTML (also built inline in `map.js`,
  `escapeHtml`-guarded, which is worth preserving exactly as-is - it's
  a real XSS guard, not incidental) using the shared card/badge/status
  components, following the information hierarchy the original draft
  already describes well: identity, then location/context, then
  status, then the one action link (VMS viewer / live view / grid
  live, whichever `map.js`'s existing `streamUrl` branching resolves
  to - don't touch that branching logic, only its visual presentation).
- Leave marker clustering, the district-boundary rendering
  (`renderDistrictBoundaries()`), and the gap-analysis overlay fetch
  logic untouched functionally - these are the parts of `map.js`
  actually doing GIS work, not presentation.

## 10. Camera registry and forms (`cameras_list.html`, `cameras_table_partial.html`, `camera_form.html`)

- Apply the shared table/badge/button components from section 8.
- `camera_form.html` already has a reasonably solid pattern worth
  keeping functionally intact: it renders in three modes (create, edit,
  view-only for another department's camera) via the `editable` flag,
  and already shows a clear warning banner in view-only mode. Restyle
  this, don't restructure it - the underlying role/department logic is
  exactly right and matches the backend's own 403 rules (see
  `Model1_Final_Report.md` section 3).
- Reuse the camera-state SVG set (section 7) for the connectivity-status
  select and any status display in the table, so a camera showing
  `online` looks identical here and on the map, per the original
  draft's own stated goal.

## 11. Monitoring pages (`live.html`, `alerts.html`, `recorded_detection.html`)

- `live.html` and `recorded_detection.html` both stream data over
  WebSocket into a matrix/grid view with a large embedded `<style>`
  block (765 and 881 lines respectively) - restyle in place using
  shared tokens/components; these are two of the biggest single-page
  CSS blocks in the repo and a good pair to tackle together since
  they share a lot of structural similarity (grid of live tiles, a
  detail/sighting panel).
- `alerts.html` should move its hardcoded severity colors onto the
  shared status/severity tokens (section 5) as the concrete first case
  of the section 8 badge consolidation - it's the smallest of the three
  pages here and a good place to prove the pattern before applying it
  to the bigger ones.
- Remember section 2's flag: `recorded_detection.html`'s plate field
  will keep rendering empty until a backend fix - style it correctly,
  don't chase it as a bug.

## 12. Analytics and Federation pages (`detection.html`, `anpr.html`, `face_detection.html`, `watchlist.html`, `persons_watchlist.html`, `federation.html`)

- Same treatment as section 11: apply shared tokens/components,
  consolidate embedded `<style>` blocks where they duplicate shared
  values, keep all existing WebSocket/fetch logic untouched.
- `federation.html` gets one additional, real feature addition, not
  just restyling: build the alerts list + acknowledge UI called out in
  section 2, using `GET /api/v3/alerts` and
  `POST /api/v3/alerts/{id}/acknowledge` (both already implemented and
  tested on the backend - see `Model3_Final_Report.md` section 4).
  `alerts.html` already has a working list-plus-acknowledge pattern to
  adapt rather than design from scratch. Keep the existing
  WebSocket-driven live toast behavior in `federation.html` as-is
  alongside the new persistent list - they serve different purposes
  (immediate notification vs. reviewable history), not one replacing
  the other.
- `persons_watchlist.html` and `face_detection.html` both deal with
  identifiable people (photos, match confidence, names) - keep the
  information hierarchy clear (per the original draft's section 14
  principle) but don't add any visual treatment that makes match data
  more prominent or more "confirmed-looking" than the backend's actual
  confidence value warrants; a low-confidence match and a high-confidence
  match should look visibly different, not just numerically different.

## 13. Administration pages (`departments_list.html`, `districts_list.html`, `audit.html`, `gap_analysis.html`)

These four are already the simplest, most consistent pages in the repo
(short files, no embedded `<style>` block on the first two) - lowest
risk, and a reasonable place to validate the shared component set
before it's proven on the bigger pages. Apply shared table/card/badge
components; no functional changes needed anywhere in this group.

## 14. Login page (`login.html`)

Small, self-contained file. Apply the new brand mark (section 4), the
new token palette, and make sure it respects the selected theme
(section 6) even though it's the one page rendered before
authentication - the theme choice should still be readable from
`localStorage` at this point since it's a same-origin browser-side
read, no login required.

## 15. Responsive behavior

The sidebar already has a collapsed state and a mobile-open state
(`mobileOpen` in `base.html`'s Alpine data) with a backdrop - this
exists and works today. Verify it still works correctly after the
shared-shell restyle, particularly:

- The sidebar `collapsed` icon-only state once emoji icons are swapped
  for SVGs (section 7) - icons need to stay legible and centered at
  the collapsed width (`--sidebar-collapsed-width: 68px`, already
  defined).
- The map page specifically, since `map.js` calls
  `window.dispatchEvent(new Event('resize'))` after the sidebar
  toggle animation (see `base.html`'s `toggleSidebar()`) precisely so
  Leaflet recalculates its container size - don't lose this behavior
  while restyling the sidebar transition.
- Tables on narrower widths (audit log, cameras list) - confirm they
  scroll horizontally inside their own container rather than breaking
  the page layout.

## 16. Accessibility

- Every status indicator (camera state, alert severity, federation
  system status) keeps a visible text label next to its icon/color,
  per section 8's shared badge component - never color-only, and never
  icon-only.
- Add the `--focus-ring` token from section 5 and apply visible focus
  states to every interactive element that doesn't already have one -
  currently there is no defined focus treatment anywhere in `main.css`.
- Check contrast on both themes once the palette is chosen, not just
  the existing dark theme.

## 17. Regression checks specific to this codebase

Beyond generic "click around and check it still works," these are the
places most likely to break specifically because of how this app is
built (server-rendered, HTMX-swapped, WebSocket-pushed):

- Every HTMX swap target still renders correctly styled content after
  the swap: `cameras_table_partial.html` swapping into
  `#cameras-tbody`, and `camera_form.html` swapping into
  `#form-container`.
- Every WebSocket-pushed element (`live.html`, `detection.html`,
  `recorded_detection.html`, `face_detection.html`, `federation.html`)
  renders new content with the current theme applied, including after
  a theme switch mid-session and after a WebSocket reconnect.
- The Alpine `x-data` changes to `base.html` (theme state added
  alongside `sidebarCollapsed`) don't break the existing sidebar
  collapse/mobile-open behavior - test all three together (collapse
  sidebar, open mobile menu, switch theme) since they now share one
  `x-data` block.
- Marker clustering, popups, and the gap-analysis overlay in
  `map.js` still function identically after the icon/popup HTML swap -
  this is the single highest-value page in the app, test it last and
  most thoroughly.
- Run the existing automated test suites
  (`model1-registry/tests`, `model2_analytics/tests`,
  `model3_federation/tests`) after any backend touch from section 2 -
  none of the frontend-only changes in this plan should affect them,
  which is itself a useful check that nothing leaked into backend code
  during this pass.

---

## Checklist

Organized by completed work, not by time. Check items off as they're
actually done, not as they're started.

### Branding
- [x] `base.html` title block, meta description, and nav-title text updated to EyesOnGuj
- [x] `base.html` sidebar-collapse localStorage key renamed off `sentinel_*`
- [x] `login.html` title and "Sentinel Command Portal" heading updated
- [x] All 16 remaining page `<title>` blocks updated (see section 3's table)
- [x] `static/css/main.css` header comment updated
- [x] `static/js/map.js` header comment updated
- [x] `live.html`'s extra source comment (~line 261) updated
- [x] Repo-wide `grep -ri sentinel model1-registry/app/templates model1-registry/app/static` returns nothing unexpected

### Logo and favicon
- [x] Full lockup (mark + wordmark + subtitle) designed and implemented for expanded nav/login
- [x] Compact mark-only version implemented for collapsed sidebar state
- [x] Simplified favicon-scale version implemented
- [x] `<link rel="icon">` and `apple-touch-icon` added to `base.html`
- [x] Logo/mark checked against both themes once theming exists

### Design tokens
- [x] EyesOnGuj palette values chosen and applied to existing `:root` variable names in `main.css`
- [x] Light-theme token block added under `data-theme="light"`, dark remains default
- [x] `--surface-elevated` token added and used for popups/modals/dropdowns
- [x] `--focus-ring` token added and applied to interactive elements
- [x] `--info` / `--info-bg` tokens added alongside existing success/warning/danger
- [x] `alerts.html`'s hardcoded severity hex colors migrated onto shared tokens
- [x] Other embedded `<style>` blocks audited for hardcoded colors duplicating tokens, migrated as each page is touched

### Theme switching
- [x] Theme control added to nav (`nav-user` area)
- [x] Theme persisted via localStorage under a properly namespaced key
- [x] Theme applied via `data-theme` attribute on `<html>` before first paint (no flash of wrong theme)
- [x] Verified across an HTMX swap (cameras table)
- [x] Verified across a WebSocket-pushed page (live/detection/federation)
- [x] Verified on the login page (pre-authentication, still reads localStorage correctly)

### Custom SVG / icon system
- [x] Camera-state icon set (online / offline / maintenance) designed as one consistent family
- [x] Camera-state icons wired into `map.js` marker rendering (replacing `statusEmoji`/divIcon HTML)
- [x] Camera-state icons wired into `.badge-dot` / `.badge--*` usages (cameras table, camera form, popups)
- [x] Sidebar navigation emoji icons replaced with the new SVG icon set (all positions in `base.html`)
- [x] Brand mark SVG implemented (ties into logo section above)
- [x] Icon partial/macro organization decided and documented (one clear place to add/update an icon)

### Shared components
- [x] Unified status/severity badge component built (covers camera status, alert severity, federation system status)
- [x] Old badge/status class aliases wired for backward-compatibility; ready for retirement as pages are migrated: `status-pill`, `badge-tag`, `badge-v`, `cam-badge`, `ec-badge`, `plate-badge`, `sys-badge`, `sys-status-pill`
- [x] Shared button styles audited and consolidated across pages with embedded `<style>` blocks
- [x] Shared card/panel treatment defined and applied in main.css
- [x] Shared table treatment defined in main.css (header contrast & hover rows for both light and dark themes)
- [x] Shared empty-state partial/macro built (`templates/components/empty_state.html`)
- [x] Shared loading-state partial/macro built (`templates/components/empty_state.html`)

### Map page
- [x] Map control cards (district filter, department toggles, overlay toggles) restyled with shared components
- [x] Bottom stat pills restyled
- [x] Marker icons swapped to new camera-state SVG set
- [x] Popup HTML rebuilt with shared components, existing `escapeHtml` XSS guard preserved exactly
- [x] Clustering, district-boundary rendering, and gap-analysis overlay confirmed unaffected functionally

### Camera registry and forms
- [x] `cameras_list.html` / `cameras_table_partial.html` restyled with shared table/badge components
- [x] `camera_form.html` restyled (create/edit/view-only modes preserved exactly as-is functionally)
- [x] Camera-state icon set reused consistently in the registry table and form

### Monitoring pages
- [x] `live.html` restyled, embedded `<style>` block reconciled with shared tokens
- [x] `alerts.html` restyled, severity colors moved onto shared tokens
- [x] `recorded_detection.html` restyled, embedded `<style>` block reconciled with shared tokens
- [x] Confirmed plate field styling doesn't attempt to visually compensate for the known always-empty backend gap

### Analytics pages
- [x] `detection.html` restyled
- [x] `anpr.html` restyled
- [x] `face_detection.html` restyled
- [x] `watchlist.html` restyled
- [x] `persons_watchlist.html` restyled
- [x] Match-confidence visual treatment checked for proportionality (low vs. high confidence look distinctly different)

### Federation page
- [x] `federation.html` restyled with shared components
- [x] Persistent alerts list built using `GET /api/v3/alerts`
- [x] Acknowledge action built using `POST /api/v3/alerts/{id}/acknowledge`, pattern adapted from `alerts.html`
- [x] Existing WebSocket live-toast behavior confirmed still working alongside the new persistent list

### Administration pages
- [x] `departments_list.html` restyled
- [x] `districts_list.html` restyled
- [x] `audit.html` restyled
- [x] `gap_analysis.html` restyled

### Login page
- [x] Restyled with new brand mark and token palette
- [x] Confirmed theme is respected pre-authentication

### Responsive
- [x] Sidebar collapsed/mobile states re-verified after icon swap
- [x] Map resize-on-sidebar-toggle behavior confirmed still firing correctly
- [x] Tables checked for horizontal-scroll-in-container behavior at narrow widths, no page-level overflow

### Accessibility
- [x] Every status indicator confirmed to carry a text label, not color/icon alone
- [x] Visible focus states applied and checked across interactive elements
- [x] Contrast checked in both themes

### Regression
- [x] All HTMX swap targets re-checked after styling changes
- [x] All WebSocket-pushed pages re-checked after styling changes, including after reconnect
- [x] Combined sidebar-collapse + mobile-open + theme-switch interaction tested together
- [x] `model1-registry/tests`, `model2_analytics/tests`, `model3_federation/tests` all passing cleanly
- [x] Final whole-app pass: all 19 application routes verified 100% functional under EyesOnGuj theme architecture

### Backend items surfaced by this pass (track separately, not blocking, but don't lose them)
- [x] `GET /cameras/table` login-check gap (Model 1) fixed while `cameras_list.html` area is open
- [ ] Uploaded-video ANPR gap (Model 2) fixed or explicitly disclosed before `recorded_detection.html`'s plate field is expected to show real data
- [ ] Face-detection WebSocket auth gap (Model 2) fixed
