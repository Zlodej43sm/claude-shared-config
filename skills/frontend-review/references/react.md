# React (and Next.js / Remix / Gatsby / React Native) review checks

Apply on top of `../SKILL.md` Step 2. Check the React major (18 vs 19) and the meta-framework first: some rules differ.

## Components and rendering
- Function components and hooks only in new code; one component per file in the project's naming family; props typed (no `React.FC` vs plain-function debate unless the project has a rule).
- Rules of Hooks: hooks at the top level, never in conditions, loops or after an early return; custom hooks start with `use`.
- No derived state in `useState` (compute it during render); no state that mirrors props without a reset strategy (`key` or controlled props).
- `useEffect` only to sync with something outside React (subscriptions, DOM, network without a data library). Data transforms, event responses and "when X changes set Y" belong in render or the event handler. Every effect has a correct dependency list (no disabled `exhaustive-deps` without a reason) and a cleanup for subscriptions, timers and aborted requests.
- Keys: stable ids from the data. `key={index}` is acceptable only for static lists that never reorder, filter or insert; flag it when items can change.
- No inline component definitions inside another component's render (they remount every render).
- Conditional rendering: `{count && …}` renders `0`; use a boolean.
- `useMemo` / `useCallback` / `React.memo` only for measured cost or referential stability that a dependency needs; React 19 with the compiler makes most of them unnecessary.
- Refs for DOM access and mutable values that don't drive render; no reading `ref.current` during render.
- Context: split by update frequency; a context value object created in render re-renders every consumer.
- Error boundaries around independent sections; `Suspense` boundaries with a meaningful fallback; no thrown promises by hand.

## Data fetching and state
- Use the project's data layer (Apollo / urql / Relay / TanStack Query / SWR / RTK Query); no ad-hoc `fetch` in `useEffect` when one exists.
- GraphQL: operations typed by codegen; generated files not edited by hand; fields queried where they are used (fragments if the project uses them); `fetchPolicy` and cache updates deliberate; `errorPolicy` decides whether a partial error blanks the UI; one failing field in a big shared query takes the whole query down.
- Apollo results are frozen in development: never mutate them (`.sort()`, `.push()`, assigning fields); copy first.
- Server state stays in the data-layer cache, not copied into a global store; global stores (Redux / Zustand / Jotai) only for real client state.
- Forms: controlled or a form library (React Hook Form, Formik) per the project; validation messages linked to inputs (`aria-describedby`).

## Next.js / SSR
- App Router: Server Components by default; `'use client'` only on the smallest interactive leaf; no server-only code (secrets, DB, `server-only` modules) imported into client components; `next/headers`/`cookies` only on the server.
- Pages Router: data in `getServerSideProps` / `getStaticProps` / the project's SSR helper; no duplicate client refetch of the same data on mount.
- Hydration: no `window`, `localStorage`, `Date`, random ids or locale formatting in render that differs server vs client; use `useId` for ids; browser-only code in `useEffect` or `dynamic(…, { ssr: false })`.
- `next/image` with sizes for images, `next/link` for internal navigation, `next/dynamic` to lazy-load heavy client widgets (modals, maps, carousels).
- Metadata / SEO through the framework API; environment variables exposed to the client only with the public prefix and only when safe.
- Caching and revalidation (`revalidate`, `fetch` cache options, route segment config) set on purpose.

## Styling
- Emotion / styled-components: styled components defined at module level, not inside render; no dynamic interpolation that creates a new class per render for frequently changing values (use CSS variables or `style`); `shouldForwardProp` for custom props so they don't reach the DOM.
- Tailwind: classes from the design tokens; `clsx`/`cva` for variants; no arbitrary values where a token exists.
- Design-system wrappers used instead of re-styling raw elements.

## Accessibility specifics
- `onClick` on a `div`/`span` needs `role`, `tabIndex` and key handlers; prefer `button`.
- Modals via the design system or a library that handles focus trap, `aria-modal`, Escape and scroll lock; focus returns to the opener.
- `eslint-plugin-jsx-a11y` warnings not silenced without a reason.

## Tests
- React Testing Library: queries by role and accessible name (`getByRole('button', { name: … })`), then label/text; `data-testid` only as a last resort; `userEvent` over `fireEvent`; `findBy…` / `waitFor` for async; no testing of state, hooks internals or class names.
- Mock the network (MockedProvider / MSW) at the boundary; render with the project's test wrapper (providers, router, intl).
- Hooks with logic get `renderHook` tests; pure helpers get plain unit tests.
- Storybook stories cover the new states (loading, empty, error, long text) when the project keeps stories.

## React Native
- `FlatList`/`FlashList` for long lists with `keyExtractor`; no `ScrollView` with many children.
- Platform differences (`Platform.select`, safe areas, keyboard avoidance) handled; accessibility props (`accessibilityRole`, `accessibilityLabel`) on touchables; touch targets ≥ 44×44 pt.
- No heavy work on the JS thread during animations (Reanimated worklets / native driver).
