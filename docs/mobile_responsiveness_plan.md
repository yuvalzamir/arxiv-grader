# Mobile Responsiveness Plan — Incoming Science Website

> Status: **planned** — not yet implemented
> Scope: all 6 pages under `website/stitch_platform_user_expansion/`

---

## Overview

The website has six pages: a landing page, four onboarding steps, and a success page.
The onboarding pages share a common shell (fixed sidebar + fixed footer) that is the primary mobile blocker.
The landing page is largely already responsive with two targeted fixes needed.
The success page needs minor polish only.

---

## 1. Landing Page (`incoming_science_how_it_works_final/code.html`)

### Fix A — Report image should be sticky, not the text

**Current:** `sticky top-32` is on the LEFT column (text). The RIGHT column (report image) scrolls.
**Fix:** Move `sticky top-32` to the right column (the `<div class="space-y-8">` that wraps the image).
Remove `sticky top-32` from the left text column — let it scroll naturally.

```html
<!-- Before -->
<div class="sticky top-32">          ← left / text
  ...text and bullets...
</div>
<div class="space-y-8">             ← right / image (scrolls)
  <img ... report_example.jpg />
</div>

<!-- After -->
<div class="">                       ← left / text (scrolls)
  ...text and bullets...
</div>
<div class="space-y-8 sticky top-32"> ← right / image (fixed while text scrolls)
  <img ... report_example.jpg />
</div>
```

### Fix B — About section has no horizontal padding

**Root cause:** The About `<section>` sits **outside** `<main>`, which is where the global
`px-8 md:px-16 lg:px-24` padding is applied. On mobile the text bleeds to the viewport edge.
**Fix:** Add `px-8 md:px-16 lg:px-24` directly to the About section:

```html
<!-- Before -->
<section class="py-24 border-t border-outline-variant/15">

<!-- After -->
<section class="py-24 border-t border-outline-variant/15 px-8 md:px-16 lg:px-24">
```

While there, also tighten the inner `max-w-2xl` constraint with a little extra padding on small screens:

```html
<!-- Before -->
<div class="max-w-2xl mx-auto text-center">

<!-- After -->
<div class="max-w-2xl mx-auto text-center px-4 md:px-0">
```

### Other landing page mobile tweaks

| Element | Current | Fix |
|---|---|---|
| Hero heading | `text-5xl lg:text-7xl` | `text-3xl sm:text-5xl lg:text-7xl` |
| Hero subtext | `text-2xl` | `text-lg md:text-2xl` |
| Hero grid | `lg:grid-cols-12` (stacks fine) | No change needed |
| Delivery cards | `md:grid-cols-2` (already responsive) | No change needed |
| Tech appendix phases | `md:grid-cols-[140px_1fr]` (stacks fine) | No change needed |
| Footer | `md:flex-row` (already responsive) | No change needed |

---

## 2. Onboarding Pages — Shared Shell (Steps 1–4)

All four onboarding pages share the same three-element shell:
- Fixed sidebar (256px wide, left)
- Main content with `ml-64` left offset
- Fixed footer with `left-64`

### Strategy: hide sidebar → inject mobile progress strip

On mobile (below `md`): the sidebar is hidden and replaced by a slim top strip showing
the current step number and a horizontal progress bar. The fixed footer expands to full width.

#### A — Sidebar

All pages should have `hidden md:flex` on the sidebar. Verify each:

| Page | Current sidebar class | Status |
|---|---|---|
| Step 1 | `fixed left-0 top-0 h-full flex flex-col ... w-64` | ❌ missing `hidden md:flex` |
| Step 2 | `fixed left-0 top-0 h-full flex flex-col ... w-64 z-50 hidden md:flex` | ✅ already correct |
| Step 3 | `fixed left-0 top-0 h-full flex flex-col ... w-64 z-50 hidden md:flex` | ✅ already correct |
| Step 4 | sidebar does NOT have `hidden md:` | ❌ missing `hidden md:flex` |

Fix Steps 1 and 4: add `hidden md:flex` and remove lone `flex` from sidebar class.

#### B — Main content left offset

All pages should use `md:ml-64` (not `ml-64`) so mobile gets no offset:

| Page | Current | Fix |
|---|---|---|
| Step 1 | `ml-64` | → `md:ml-64` |
| Step 2 | `md:ml-64` | ✅ already correct |
| Step 3 | check — likely `ml-64` | → `md:ml-64` |
| Step 4 | check — likely `ml-64` | → `md:ml-64` |

#### C — Fixed footer left offset

All pages should use `left-0 md:left-64` so footer spans full width on mobile:

| Page | Current | Fix |
|---|---|---|
| Step 1 | `fixed bottom-0 left-64 right-0 h-20 px-12` | → `left-0 md:left-64 px-4 md:px-12` |
| Step 2 | same pattern | same fix |
| Step 3 | same pattern | same fix |
| Step 4 | same pattern | same fix |

#### D — Mobile progress strip (add to all 4 pages)

Insert this block immediately after `<body>` opening (before sidebar), visible only on mobile:

```html
<!-- Mobile-only step indicator (hidden on md+) -->
<div class="md:hidden fixed top-0 left-0 right-0 z-50 bg-surface-container-lowest border-b border-outline-variant/20">
  <div class="h-[2px] bg-outline-variant/20 w-full">
    <div class="h-full bg-primary" style="width: 25%"></div>  <!-- 25% / 50% / 75% / 100% per step -->
  </div>
  <div class="px-4 py-2 text-xs font-label uppercase tracking-widest text-on-surface-variant">
    Step XX of 04  <!-- fill per page -->
  </div>
</div>
```

Step widths:
- Step 1: `width: 25%`
- Step 2: `width: 50%`
- Step 3: `width: 75%`
- Step 4: `width: 100%`

Also add `pt-10 md:pt-0` to main content wrapper so it clears the mobile strip.

---

## 3. Per-Page Changes (beyond the shared shell)

### Step 1 — Identity & Delivery

| Element | Fix |
|---|---|
| Hero heading `text-[3.5rem]` | → `text-2xl md:text-[3.5rem]` |
| Form card `p-8 md:p-12` | → `p-6 md:p-12` |
| Delivery toggles `grid-cols-1 md:grid-cols-2` | ✅ already correct |
| Content padding `px-8 md:px-12` | → `px-4 md:px-12` |

### Step 2 — Research Field

| Element | Fix |
|---|---|
| Two-column `col-span-12 lg:col-span-7/5` | ✅ already stacks correctly |
| Content area `px-8 md:px-12` | → `px-4 md:px-12` |
| Dropdown `text-lg` | fine as-is |

### Step 3 — Signals & Interests

| Element | Fix |
|---|---|
| Hero heading | → `text-2xl md:text-[3.5rem]` |
| Bottom aside `flex-col md:flex-row` | ✅ already correct |
| Bento cards — check for horizontal overflow on mobile | add `overflow-hidden` if needed |
| Content padding | → `px-4 md:px-12` |

### Step 4 — Seed Papers

| Element | Fix |
|---|---|
| Two-column `col-span-12 lg:col-span-5/7` | ✅ already stacks correctly |
| Hero heading | → `text-2xl md:text-[3.5rem]` |
| Textarea height `h-80` | → `h-48 md:h-80` |
| Decorative material icon `text-[120px]` | → `text-[60px] md:text-[120px]` |
| Content padding | → `px-4 md:px-12` |

---

## 4. Success Page (`onboarding_success_final/code.html`)

The success page has no sidebar, so no shell changes needed.

| Element | Fix |
|---|---|
| Main grid `lg:grid-cols-12` | ✅ stacks correctly below lg |
| Hero heading `text-5xl` | → `text-3xl lg:text-5xl` |
| JSON display block `bg-[#041627]` | add `overflow-x-auto` so long JSON lines scroll on mobile |
| Container `px-6` | ✅ fine |
| Fixed footer | `px-4 md:px-12` |

---

## 5. Implementation Order

1. **Landing page fixes** — sticky image, about section padding, hero font (3 files, ~10 lines)
2. **Shared shell** — sidebar `hidden md:flex`, `md:ml-64`, footer `left-0 md:left-64` (4 pages, mechanical)
3. **Mobile progress strip** — add 4 copies (one per onboarding page)
4. **Per-page tweaks** — typography, padding, textarea height (4 pages, ~6–10 lines each)
5. **Success page** — 4 tweaks
6. **Test on mobile** (Chrome devtools 375px + real device if available)

---

## 6. Files to change

| File | Changes |
|---|---|
| `incoming_science_how_it_works_final/code.html` | Sticky fix, about padding, hero font |
| `onboarding_identity_delivery_final/code.html` | Shell fix, progress strip, per-page tweaks |
| `onboarding_research_field_final/code.html` | Shell fix (partial), progress strip, padding |
| `onboarding_signals_interests_final/code.html` | Shell fix, progress strip, per-page tweaks |
| `onboarding_seed_papers_final/code.html` | Shell fix, progress strip, textarea, icon |
| `onboarding_success_final/code.html` | Font, JSON overflow, footer padding |
