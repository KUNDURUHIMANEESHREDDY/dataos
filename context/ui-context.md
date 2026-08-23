# DataOS — UI Context

## Theme

**DataOS Dark Technical Workspace** — Near-black backgrounds, layered surfaces, and vivid accent colors for interactive elements. No light mode. The design language reflects DataOS as a professional data operating system, not a consumer application.

- **Dark Mode Only** — `#0a0a0f` base, `#141418` surfaces, `#1e1e26` panels
- **Accent Palette** — Single accent maximum, saturation < 80% (per frontend-dev skill rules)
  - Primary: `#d97757` (orange, per brand override rules)
  - Secondary: `#6a9bcc` (blue, used sparingly)
  - Success: `#788c5d` (green, for positive metrics)
  - Error: `#d15b47` (red, for errors/critical)

## Colors

**CSS Custom Properties** — All components must use these tokens; no hardcoded hex values in component files.

| Role | CSS Variable | Value | Description |
|------|--------------|-------|-------------|
| Page background | `--bg-base` | `#0a0a0f` | Full-page background |
| Surface | `--bg-surface` | `#141418` | Cards, panels, modals |
| Surface elevated | `--bg-surface-elevated` | `#1e1e26` | Modal backs, dropdown bodies |
| Primary text | `--text-primary` | `#faf9f5` | Main readable text |
| Muted text | `--text-muted` | `#b0aea5` | Secondary text, hints, disabled |
| Primary accent | `--accent-primary` | `#d97757` | Buttons, active states, highlights |
| Border default | `--border-default` | `#2a2a3a` | Input borders, dividers |
| Error state | `--state-error` | `#d15b47` | Errors, validation failures |
| Success state | `--state-success` | `#788c5d` | Successful operations, positive metrics |
| Warning state | `--state-warning` | `#f0ad4e` | Warnings, attention markers |

**Color Usage Rules (per frontend-dev skill):**
- Max 1 accent color at any time
- Saturation < 80% for all accents
- Never use AI purple/blue (#6f42c1, #8b5cf6, etc.)
- Accessibility: contrast ratio ≥ 4.5:1 for normal text, ≥ 3:1 for large text
- `prefers-reduced-motion` respecting — no color-based animation cues only

## Typography

**Font Family** — Geist, Outfit, Satoshi (per frontend-dev skill typography rules; never Inter on dashboards)

| Role | Font | CSS Variable | Priority |
|------|------|--------------|----------|
| UI text (headers, labels) | Geist Sans / Outfit | `--font-sans` | 1st choice |
| Body text | Geist Sans / Outfit | `--font-sans` | 1st choice |
| Code/monospace | Geist Mono | `--font-mono` | 2nd choice |
| Headings | Geist, tracking-tighter | `--font-sans` | `text-4xl md:text-6xl tracking-tighter` |

**Typography Scale** (per frontend-dev skill rules):
- Headlines: `text-4xl md:text-6xl tracking-tighter` (Geist, tracking-tighter)
- Body: `text-base leading-relaxed max-w-[65ch]` (Geist, leading-relaxed)
- Never use Inter font
- Never use Serif on dashboards
- Max 65ch width for body text

**Vertical Rhythms** — `min-h-[100dvh]` not `h-screen`; CSS Grid not flex percentage math; `max-w-[1400px] mx-auto` or `max-w-7xl`.

## Border Radius

| Context | Class Pattern | Example |
|---------|--------------|---------|
| Inline / small UI | `rounded-[size]` | `rounded-[0.5rem]` |
| Cards / panels | `rounded-[size]` | `rounded-[1rem]` |
| Modals / overlays | `rounded-[size]` | `rounded-[1.5rem]` |
| Avatars / avatars small | `rounded-full` | `rounded-full` |
| Tabs / pill elements | `rounded-[size]` | `rounded-[0.75rem]` |

**Border Radius Scale** (per frontend-dev skill):
- `rounded-[0.25rem]` — small inputs, icons
- `rounded-[0.5rem]` — default buttons, small cards
- `rounded-[0.75rem]` — tabs, section headers
- `rounded-[1rem]` — cards, panels default
- `rounded-[1.5rem]` — modals, large cards
- `rounded-[2.5rem]` — page surfaces (per brand override: `rounded-[2.5rem]`)

**Never use** `border-white/10` alone — must combine with `backdrop-blur` per liquid glass rule.

## Component Library

**Base Library** — shadcn/ui on top of Tailwind CSS v4. All components live in `components/ui/`; use the CLI to add new components rather than writing from scratch.

**Core Components (shadcn/ui adapted for DataOS):**
- `button` — primary/secondary/variants; Framer Motion hover states; magnetic button pattern when MOTION_INTENSITY > 5
- `card` — `border-t`, `divide-y`, or spacing based on VISUAL_DENSITY; never generic cards when DENSITY > 7
- `input` — label above input, error below, `gap-2` for input blocks; skeleton loading state
- `dropdown-menu` — CSS only hover/focus states; no GSAP + Framer mixing
- `progress` — animate only `transform` and `opacity` (GPU-only properties)
- `alert` — `scale-[0.98]` tactile feedback on focus; Loading, Empty, Error states always implemented
- `avatar` — `rounded-full`; circular crop ready; Phosphor or Radix icons only (no emojis)
- `tooltip` — follow `prefers-reduced-motion`; visible focus rings via `outline` not `box-shadow`

**DataOS-Specific Components:**
- `object-browser` — Hierarchical tree of universal objects with relation toggles
- `graph-visualizer` — Three.js-based graph with drag-to-pan, zoom, multi-hop highlighting
- `provenance-panel` — Side panel showing full lineage tree from inputs to current object
- `query-builder` — Natural language + structured query construction with preview
- `workflow-canvas` — Drag-and-drop trigger→conditions→actions→outputs pipeline builder
- `data-profile` — Profiling metrics display with distributions, outliers, correlations
- `quality-gates` — Validation results visualization with pass/fail indicators
- `schema-evolution` — Timeline view of schema changes with impact analysis

## Layout Patterns

| Pattern | Description | Usage in DataOS |
|---------|-------------|-----------------|
| **Editor** | Full-viewport split with left sidebar, center canvas, right sidebar | Data browser (left), graph area (center), provenance/query (right) |
| **Sidebars** | Fixed width with border separator | Object browser fixed at `w-[260px]`; query panel fixed at `w-[340px]` |
| **Modals** | Centered overlay with backdrop blur | Provenance details, schema editor, relationship creation |
| **Navbar** | Top bar with bottom border | DataOS branding, user menu, new object button, search toggle |
| **Bento Grid** | Asymmetric grid with variance control | Dashboard layouts; VARIANCE > 4 forces split-screen/asymmetric |
| **Horizontal Carousel** | Infinite horizontal carousel | Large data profile charts, recent activity stream |
| **Split-Screen** | Forced when VARIANCE > 4 | Asymmetric layouts when design variance high; no centered heroes |
| **Sticky Header** | Header stays on scroll | Maintains access to object browser, search, new import |

**Layout Constraints (per frontend-dev skill):**
- `min-h-[100dvh]` not `h-screen`
- `max-w-[1400px] mx-auto` or `max-w-7xl`
- `px-4` for mobile layout collapse (`w-full`)
- Cards omitted where spacing suffices (per DENSITY rules)
- `gap-2` for input blocks; label above input; error below

## Icons

**Icon Set** — Lucide React. Stroke-based icons only, consistent visual weight.

| Size | Usage |
|------|-------|
| `h-4 w-4` | Inline icons, list items |
| `h-5 w-5` | Buttons, menu items |
| `h-6 w-6` | Cards, section headers |
| `h-8 w-8` | Toolbar buttons, large callsout |

**Icon Rules (per frontend-dev skill):**
- Stroke-based only — no filled icons
- Never use emojis anywhere (blocking error)
- Phosphor or Lucide preferred over custom icon sets
- Consistent stroke width across all icons
- Inactive/invalid icons at 50% opacity

**DataOS Icon Categories:**
- `folder` — object container, project, dataset
- `file` — document, PDF, CSV, media
- `database` — table, column, view
- `graph` — relationship, connection, link
- `search` — search, filter, find
- `provenance` — lineage, trace, origin
- `play` — execute, compute, run
- `settings` — schema, permissions, configuration
- `export` — download, share, portability
- `delete` — remove, discard, delete (with confirmation)

## Design Dials (Per frontend-dev skill SKILL.md)

These are design parameters that can be adjusted per project context:

| Dial | Default | Range | Description |
|------|---------|-------|-------------|
| **DESIGN_VARIANCE** | 8 | 1=Symmetry, 10=Asymmetric | Forces asymmetric layouts when > 4; avoids centered heroes |
| **MOTION_INTENSITY** | 6 | 1=Static, 10=Cinematic | Controls animation density; 5-6 normal, 7-8 cinematic, 9-10 immersive |
| **VISUAL_DENSITY** | 4 | 1=Airy, 10=Packed | Controls card density; DENSITY > 7 use `border-t`/`divide-y` instead of generic cards |

**Current DataOS Settings:**
- DESIGN_VARIANCE: 8 (asymmetric layouts encouraged; no centered heroes)
- MOTION_INTENSITY: 6 (subtle to smooth animations; Framer Motion for enter/exit, GSAP for scroll)
- VISUAL_DENSITY: 4 (airy layout; cards used judiciously; spacing over card overuse)

## Accessibility (Non-Negotiable)

- `prefers-reduced-motion` respecting — **ALWAYS** wrap motion in this check
- **NEVER** flash content > 3 times/second (seizure risk)
- **ALWAYS** provide visible focus rings — use `outline` not `box-shadow`
- **ALWAYS** add `aria-live="polite"` for dynamically revealed content
- **ALWAYS** include pause button for auto-playing animations
- Focus rings: `outline-2 outline-offset-2 outline-primary-accent` on focus
- Skip links for navigation
- Color contrast: ≥ 4.5:1 normal, ≥ 3:1 large text
- All motion has reduce-prefers-motion variant (disabled when user enables)