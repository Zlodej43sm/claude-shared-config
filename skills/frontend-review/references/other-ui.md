# Other UI stacks review checks

Apply on top of `../SKILL.md` Step 2.

## Svelte / SvelteKit
- Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`) in new code when the project is on Svelte 5; `$derived` for computed values, `$effect` only for side effects with cleanup.
- `{#each items as item (item.id)}` keyed blocks; no `{@html}` with unsanitised data.
- SvelteKit: data in `load` functions (`+page.server.ts` for secrets and DB, `+page.ts` for universal); form actions for mutations with progressive enhancement; no browser-only APIs during SSR (`browser` from `$app/environment`, `onMount`).

## SolidJS
- Don't destructure props (breaks reactivity; use `splitProps`/`mergeProps`); signals called as functions in JSX; `createMemo` for derived values; `<For>`/`<Show>` instead of `.map`/ternaries for reactive lists; `createResource` for async data with `Suspense`.

## Web components (Lit, Stencil, vanilla custom elements)
- Reactive properties declared (`@property` / `@state`); attributes reflect only when needed; events dispatched with `bubbles` and `composed` when they must cross the shadow root.
- Shadow DOM accessibility: labels and ARIA relationships can't cross shadow boundaries; use `ElementInternals` for form-associated elements; focus delegation (`delegatesFocus`).
- Clean up listeners and observers in `disconnectedCallback`; no work in the constructor that needs attributes or children.
- Styles via `static styles` / constructable stylesheets; theming through CSS custom properties and `::part`.

## Plain HTML/CSS/JS and server-rendered templates
- Semantic HTML first; forms work without JS where possible (progressive enhancement); `<label for>` on inputs; `lang` on `<html>`.
- Templates escape output by default; no raw/unescaped filters (`|raw`, `|safe`, `<%==`, `{{{ }}}`) on user or API data.
- JS: event delegation for repeated elements; no global variables; `defer`/`type="module"` scripts; no blocking scripts in `<head>`; DOM updates batched; `textContent` instead of `innerHTML` for text.
- CSS: design tokens / custom properties; no `!important` in new code; logical properties for RTL; mobile-first media queries; `prefers-reduced-motion` respected for animations.
- Assets: images with `width`/`height`, `loading="lazy"` below the fold, `srcset`/`sizes`; fonts with `font-display`.

## Mobile (React Native, Flutter, native webviews)
- Touch targets ≥ 44×44 pt; screen-reader labels and roles on custom controls; dynamic type / font scaling doesn't clip text.
- Safe areas, keyboard avoidance and orientation handled; offline and slow-network states.
- Long lists virtualised; images cached and sized; no heavy work on the UI thread.
- Deep links and back navigation behave; analytics screen names updated.
