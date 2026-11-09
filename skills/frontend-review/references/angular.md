# Angular review checks

Apply on top of `../SKILL.md` Step 2. Check the Angular major in `package.json`: standalone components, signals and the built-in control flow (`@if`, `@for`) are the default in recent versions; follow what the project already uses.

## Components and templates
- Standalone components (or the project's module structure, consistently); one component per file; selector prefix per `angular.json`.
- `ChangeDetectionStrategy.OnPush` on new components (or zoneless with signals); no manual `detectChanges` to paper over a data-flow problem.
- Signals for local state (`signal`, `computed`, `effect` only for side effects outside Angular); `input()` / `output()` / `model()` functions in new code where the version supports them; inputs typed and `required` when mandatory.
- Templates: built-in control flow; `@for` with `track` on a stable id (`trackBy` in `*ngFor`); no function calls or heavy expressions in bindings (use `computed` or pure pipes); no `any` through `$any()`.
- Smart vs presentational split: presentational components get data by inputs and emit outputs; no service injection for data they could receive.
- `@defer` for heavy below-the-fold blocks; lazy-loaded routes (`loadComponent` / `loadChildren`).

## RxJS and data
- No nested `subscribe`; compose with operators (`switchMap` for latest-wins requests, `concatMap` for ordered writes, `exhaustMap` for submit buttons).
- Every subscription ends: `async` pipe, `toSignal`, `takeUntilDestroyed()`; no manual subscriptions without teardown.
- HTTP through services and `HttpClient`; interceptors for auth and errors; typed responses; errors handled with `catchError` and a user-visible state.
- Store (NgRx / signals store / services): server state not duplicated across stores; selectors memoised; no business logic in components.
- `inject()` or constructor injection consistently; services `providedIn: 'root'` unless scoped on purpose.

## Forms
- Reactive forms (typed `FormGroup`/`FormControl`) for non-trivial forms; validators in the form model, not in the template; error messages linked to inputs and announced.

## SSR and hydration (Angular Universal / `@angular/ssr`)
- No direct `window`, `document` or `localStorage` access; use `isPlatformBrowser`, `afterNextRender` or injected tokens; hydration-safe markup (no DOM manipulation outside Angular).
- `TransferState` / HTTP transfer cache so the client doesn't refetch server data.

## Security
- No `bypassSecurityTrust*` on API or user data; no `[innerHTML]` without sanitising; Angular's built-in sanitisation kept on.

## i18n
- `@angular/localize` (`i18n` attributes, `$localize`) or the project's library (Transloco, ngx-translate) for every user-facing string; ICU for plurals; locale-aware pipes (`date`, `currency`, `number`) with the right locale and time zone.

## Styling
- Component styles scoped (default emulated encapsulation); no `::ng-deep` in new code; design-system components and tokens; Angular Material / CDK a11y helpers (`cdkTrapFocus`, `LiveAnnouncer`) where relevant.

## Tests
- `TestBed` with standalone imports or Angular Testing Library; test through the DOM (roles, labels); `HttpTestingController` for HTTP; `fakeAsync`/`tick` or `await fixture.whenStable()` instead of real timers; harnesses for Material components.
- No tests that only assert the component was created.
