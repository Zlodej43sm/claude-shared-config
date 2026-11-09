---
name: frontend-review
description: Review front-end / UI code (a PR, a branch or a local diff) for any UI stack - React, Next.js, Angular, Vue, Nuxt, Svelte, SolidJS, Lit / web components, React Native or plain HTML/CSS/JS. Detects the stack and its libraries first (framework, rendering mode, data layer, styling, i18n, test tools), then applies UI-wide checks (API data contract and release order, loading/empty/error states, accessibility, i18n, rendering and hydration, state and data fetching, performance, security, design system, analytics, tests) plus the best practices of the detected framework from references/. Use when a change touches UI code, alone or inside pr-review (the pr-reviewer agent applies it to the frontend bucket). Read-only - never posts unless asked.
---

# frontend-review — review UI code against the stack's best practices

Generic and reusable: no company or project data lives here. The rules come from three places, read every time:
1. This skill: Step 2 (any UI stack) and the reference file for each detected framework (Step 0).
2. The project's own rules: follow the root `CLAUDE.md` / `AGENTS.md` (workspace and repo) to its front-end conventions, `CONTRIBUTING.md` (review guidelines, PR title rules), lint config and design-system docs.
3. `../test-design/SKILL.md` for every test change.

Order of authority: repo `CLAUDE.md` / `CONTRIBUTING.md` → project docs and lint config → the framework reference → Step 2. A finding cites the rule it breaks (doc path + section, or skill section). A rule the project's lint already enforces in CI is not a finding unless CI would fail.

## Step 0 — detect the UI stack
Read `package.json` (dependencies and scripts), the lock file name, and the config files at the repo root. Record each line below; it decides which checks apply.

| Look for | Means | Reference |
|---|---|---|
| `react`, `react-dom`, `*.jsx`/`*.tsx` | React | `references/react.md` |
| `next` (`app/` = App Router, `pages/` = Pages Router), `@remix-run/*`, `gatsby` | React meta-framework (SSR/SSG) | `references/react.md` (§Next.js / SSR) |
| `react-native`, `expo` | React Native | `references/react.md` + `references/other-ui.md` §Mobile |
| `@angular/core`, `angular.json` | Angular (check the major: signals, standalone, control flow) | `references/angular.md` |
| `vue`, `*.vue`, `nuxt` | Vue / Nuxt | `references/vue.md` |
| `svelte`, `@sveltejs/kit`, `solid-js`, `lit`, `customElements.define`, `@stencil/core` | Svelte, Solid, web components | `references/other-ui.md` |
| none of the above, only `*.html`/`*.css`/`*.js`, templates (`*.twig`, `*.erb`, `*.hbs`, `*.jinja`) | plain UI / server templates | `references/other-ui.md` §Plain |

Also note: TypeScript strictness; data layer (Apollo / urql / Relay + GraphQL codegen, TanStack Query, SWR, RTK Query, NgRx, Pinia, signals); styling (CSS modules, Emotion / styled-components, Tailwind, SCSS, a design-system package); i18n library (react-intl / FormatJS, i18next, `@angular/localize`, vue-i18n) and where translation files live; test tools (Jest / Vitest, Testing Library, Storybook, Playwright / Cypress, visual tests); feature-flag and analytics clients. Read the matching reference file(s) before Step 2.

## Step 1 — scope
- Get the diff against the base, the PR description, screenshots and existing review threads. Read each changed component whole, plus its parent, its children, its styles, stories, fixtures and tests.
- Find every other user of a changed component, hook, query, fragment or shared type (`grep` the import path and the exported name). A changed prop or query shape breaks callers the diff doesn't show.
- A UI that renders a new API field: read the provider PR or schema (its field names, nullability and what it actually returns, not only the type), and check whether it is in production. Pinned or hand-edited schemas must match the provider.
- Bot comments: check each against the current head before relying on it.

## Step 2 — check, in this order
1. **API data contract and release order.** Every queried field exists in the deployed API, or the PR says it must wait for the provider release. With GraphQL, one unknown field fails the whole operation, so new fields in a shared page query can blank the whole section: ask for a separate query or a release gate. Generated types come from the provider's real schema (re-pulled, not hand-edited; no fields the provider doesn't have). Nullable fields are handled. Fixtures match what the API really returns (shapes and typical values, such as empty lists), not only the happy path.
2. **States.** Loading, empty, error and partial data each render something deliberate; no layout shift while loading; errors don't take down sibling sections (error boundary or a local fallback); retries and refetch don't duplicate data.
3. **Accessibility** (WCAG 2.2 AA). Semantic elements (`button` for actions, `a` for navigation, headings in order, lists as lists); every interactive element is reachable and usable by keyboard with a visible focus; dialogs trap and restore focus, close on Escape, have a name (`aria-labelledby`); images have `alt` (empty for decorative); form inputs have labels and announced errors; colour is not the only signal; `aria-*` only where native semantics can't do it; emphasis uses `strong`/`em`, not only styling; text scales without clipping.
4. **Internationalisation.** No hard-coded user-facing strings (unless the copy comes from an API on purpose, which the PR says); one message per full sentence with placeholders, never concatenated fragments; plurals and genders via ICU/library features; dates, numbers and currencies through locale-aware formatters with the right time zone; text with offsets (highlight ranges) is safe for every locale the API returns; removed keys are deleted or moved per the project's translation workflow; new keys added to every locale file the project requires; RTL-safe layout (logical CSS properties) if RTL locales are supported. A component that now takes copy from an API while siblings still use translation keys for the same text (a button label and its dialog title) can drift: ask which is the source of truth.
5. **Rendering, SSR and hydration.** Server and client render the same markup (no `Date.now()`, `Math.random()`, `window`, locale or time-zone-dependent output during render); browser-only code runs after mount or behind a client boundary; data fetched on the server isn't fetched again on the client; SEO-relevant content is server-rendered; no secrets or server-only modules in client bundles.
6. **State and data flow.** Props are minimal and typed from the generated/shared types (no `any`, no casts hiding a mismatch); no derived state copied into state; no prop drilling where the project uses a store or context; cache updates after mutations; queries co-located with the component that uses them (fragments) where the project does that; no request waterfalls; no fetch inside loops.
7. **Performance.** Bundle impact of new dependencies (size, tree-shaking, a lighter existing one); lazy-load heavy, below-the-fold or rarely opened UI (modals, charts); images sized, lazy and in modern formats; lists keyed by stable ids, virtualised when long; no expensive work on every render; no memoisation without a measured need; Core Web Vitals (LCP, CLS, INP) not harmed.
8. **Security.** No raw HTML injection (`dangerouslySetInnerHTML`, `[innerHTML]`, `v-html`, `{@html}`, `innerHTML`) of API or user data without sanitising; URLs from data checked before `href`/`src` (`javascript:`); external links `rel="noopener noreferrer"`; no tokens or personal data in URLs, local storage or logs; CSP-friendly (no inline `eval`).
9. **Design system and styling.** Use the project's design-system components and tokens (spacing, colour, typography) instead of new raw CSS values; no one-off copies of an existing component; responsive at the project's breakpoints; dark mode / themes if supported; styles scoped (no global leaks); matches the design (screenshot or Figma in the PR).
10. **Analytics, flags and experiments.** Tracking events kept or updated when UI moves or changes; event names and payloads follow the tracking plan; feature flags default safely and the old path is removed when the flag is.
11. **Tests** (apply `../test-design/SKILL.md`). Test behaviour through the user's view (Testing Library roles and names, not class names or implementation details); one test per behaviour at the lowest level (component test over E2E for rendering branches); fixtures realistic (the payload shape the API really sends today is covered); no snapshot-only tests for logic; async UI awaited (`findBy…`), no fixed sleeps; mocks for network at the boundary (MSW / mocked provider), not of the component's own children; stories updated for new props/states; E2E or visual checks the project requires before release are done or explained.
12. **Code quality.** Components small and single-purpose; file and folder naming in the project's family; no dead props, styles, translations or exports left after a refactor; no commented-out code; no drive-by changes; PR description matches the code (screenshots for visual changes).

## Step 3 — report
- Findings ranked: **blocking** (broken page or flow, contract mismatch with the deployed API, a11y blocker on a primary flow, XSS, hydration error), **should fix** (stack best practice or project rule), **should-fix (decision needed)** (see below), **suggestion** / **[nit]**, **test-gap**, **question**. Each finding: `file:line` — what is wrong (rule cited) — **How it can fail** (a concrete user, locale, device, payload or timing) — **Solution proposal** (code or a `suggestion` block).
- Ask instead of asserting when the design intent is unclear ("Should the end date be bold? The API sends no emphasis today.").
- A should-fix that needs the author, design or product to choose first (which copy is the source of truth, is the design right, should two places agree) is labelled `should-fix (decision needed)` in the review only. Its comment text is written the way a human reviewer would: short, plain words, only the facts needed to answer, one question, at most one suggested way forward, and no label, emoji, bold, heading, rule citation or "How it can fail" / "Solution proposal" parts ("The fixture makes the end date bold, but the API never sends emphasis, so it won't be bold in production. Should it be? If so, the API needs to send the range."). When posted, it goes out as that plain text alone. Every other finding keeps its usual label and format.
- A finding about the PR description, not a file, is a general comment.
- Don't flag what the project docs mark as accepted, and don't re-raise points already answered in the threads.
- Read-only: don't edit code, don't post comments, don't resolve threads unless the user asks.
