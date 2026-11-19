# APEX Design System

## Direction

APEX uses an Apple-inspired, quiet, premium interface with restrained translucent
materials. Clarity and information hierarchy take priority over decoration.

## Visual rules

- Use the system font stack and the shared type scale. Body copy remains readable
  at 13–15 px; secondary text never relies on extreme low contrast.
- Use shared spacing, radius, border, shadow, material, color, duration, and easing
  tokens from `frontend/apex-design-tokens.css`.
- Use glass materials for navigation, floating controls, drawers, modal chrome,
  and toolbars. Use solid or lightly translucent surfaces for dense tables, long
  forms, legal text, and scrolling lists.
- One screen has one primary action. Destructive actions are visually distinct and
  require the existing confirmation behavior.
- Motion explains state changes. Keep it brief and disable nonessential motion when
  `prefers-reduced-motion` is active.
- Respect `prefers-reduced-transparency`; glass surfaces must remain legible without
  backdrop blur.

## Component behavior

- Inputs, buttons, selectors, drawers, dialogs, toasts, loading states, and empty
  states use shared primitives before feature-specific CSS is added.
- Focus rings are always visible for keyboard use. Hover alone must not expose a
  required action.
- Shared controls keep identical label placement, hit targets, disabled treatment,
  loading treatment, error language, and keyboard semantics across pages.
- New colors, radii, shadows, or spacing values require a token or an explicit
  feature-specific reason in the change description.
- For inset selection and hover surfaces that follow the enclosing corners,
  derive the inner radius from the outer radius minus both the frame border
  and the inset padding. Moving selection layers use the same radius and
  bounds as the button they highlight.

## Review views

Long case names, filenames, paths and status messages must be included in layout
checks. Flex/grid content may shrink and wrap while action controls keep readable
labels. An intentional table/toolbar scroller owns its overflow; it must not widen
the surrounding page or shrink buttons into clipped text. Selected attachments
and composer controls need distinct space in narrow layouts. A clamped title
retains its complete accessible text and a full-name tooltip.

Desktop layout takes priority. Mobile layout changes must also pass desktop
window, fullscreen, drawer and history-column checks before acceptance. The AI
composer keeps its integrated desktop card above 760 px, including 960 px Mac
windows. History owns a separate column; a narrow remaining pane uses two control
rows regardless of monitor width. Text, attachments and controls reserve separate
space, and hint actions wrap as whole buttons. Test both sides of responsive
boundaries, attached files, multiline input, light/dark and Chromium/WebKit.

Visual regression uses 1440×900 and 1024×768 in light and dark appearance. The
baseline set covers the home page, case manager, client picker, a document
generator, AI workspace, and personal center. Real client and case data must be
replaced with anonymous fixtures before capturing a baseline.

