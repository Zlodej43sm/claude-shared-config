# Vue (and Nuxt) review checks

Apply on top of `../SKILL.md` Step 2. Check the Vue major (2 vs 3) and whether the project uses the Composition API with `<script setup>` or the Options API; follow the project's style.

## Components
- Single-file components named in PascalCase, multi-word (`UserCard`, not `Card`); `<script setup lang="ts">` in new Vue 3 code when the project uses it.
- Props typed with `defineProps<…>()` and defaults via `withDefaults`; never mutate a prop (emit an event or use `defineModel`); events declared with `defineEmits`.
- `computed` for derived values, not `watch` + state; `watch` / `watchEffect` only for side effects, with cleanup (`onWatcherCleanup` / return value) and `immediate`/`deep` set on purpose.
- Reactivity: don't destructure a `reactive()` object or props without `toRefs` / reactive props destructure (Vue 3.5+); `ref` for primitives; `shallowRef` for large immutable data.
- `v-for` always with `:key` on a stable id; never `v-if` on the same element as `v-for` (filter in a `computed`).
- Composables (`useX`) for shared logic; no mixins in new Vue 3 code.
- `defineAsyncComponent` / lazy routes for heavy, rarely shown UI.

## State and data
- Pinia (or the project's store) for shared client state; server state through the project's data layer (Nuxt `useFetch`/`useAsyncData`, TanStack Query, Apollo); no duplicate copies of server data in stores.
- Nuxt: `useFetch` / `useAsyncData` with a unique key so SSR data is reused on the client; `$fetch` only in event handlers; `useState` for SSR-safe shared state; server routes for secrets.

## SSR and hydration
- No `window`/`document` during setup on the server; use `onMounted`, `<ClientOnly>` or `import.meta.client`; render output identical on server and client (dates, random ids → `useId`).

## Security
- No `v-html` with API or user data unless sanitised; URLs from data checked before binding to `href`/`src`.

## i18n
- `vue-i18n` / `@nuxtjs/i18n` (or the project's library) for every user-facing string; pluralisation via the library; `$d` / `$n` or `Intl` for dates and numbers.

## Styling
- `<style scoped>` or CSS modules; `:deep()` only with a reason; design-system components and tokens.

## Tests
- Vue Test Utils or Vue Testing Library (prefer queries by role/text); `await` after interactions (`await wrapper.trigger(...)`, `flushPromises`); mock the network at the boundary; Pinia via `createTestingPinia`; no tests of internal component state.
