# Logging — quick reference (generic)

Read before adding, changing or reviewing a log line or an error that will be logged. The project's logging guideline wins where it is more specific (logger package, error classes, automatic log names, lint rules); its local summary is linked from the project's coding-standards docs.

Logs serve three jobs: detect unexpected situations (alerts), debug one error, analyse usage. Every rule below keeps them cheap to search and safe to keep.

## Errors are logged from what you throw
- The framework logs thrown errors and error responses. So throw with enough context instead of logging first: put every variable needed to reproduce the failure (all inputs of the failing call) in the error's structured `info`, and keep the original error as `cause`.
- Use the error type that fits the protocol: an HTTP error with a status for REST routes, a GraphQL error with a code for GraphQL, the project's base error class (with `info` + `cause`) for RPC methods, jobs and models.
- Static messages: `'Payment failed'` + `info: { orderId }`, never `` `Payment failed for ${orderId}` `` (dynamic text breaks grouping of the same error).
- Don't add an error log for a failure the framework already logs as an error response; enrich the context instead (next section).

## One structured logger, few fields
- Always the project's structured (JSON) logger, never `console.log` (not parsed by the log pipeline).
- Need context on later logs? Add fields to the logger, or create a child logger with them; don't write a log line only to carry context.
- Log the few fields you need (ids, types, counts, status), never a whole object or payload: every property becomes an index field (the index can hit its field limit and stop indexing new logs), you rarely need all of it, and objects you don't control leak personal data.
- Exception: when you really need a heavy object, put it in one field as a string (`{ payloadJson: JSON.stringify(obj) }`). Exception, not default; never for objects that may hold personal data.
- Keep an existing log line unless it is wrong; don't replace it with a summariser function.
- Don't log what the platform adds to every line (environment, application, caller, request ids).

## Know the automatic logs
- Frameworks usually log: request/response end (info), the same with payload and response at debug level, error responses with the request payload (error), outbound call end and error, job end and job failure. Find their names/fields in the project guideline before adding your own; never duplicate them.

## Sensitive data
- Never log passwords, tokens, keys, personal data. Don't log objects you don't control; don't put sensitive data into errors you throw (they get logged later).
- Filter request and client payloads with the framework's payload-transform hook (mask `password`, `token`, `jwt`…) when the platform logs payloads.

## Levels
| Level | Use | Example |
|---|---|---|
| DEBUG | extra detail for debugging; never enabled in production | request payload sent to a dependency |
| INFO | what is happening; outcomes worth a dashboard | booking created / failed, with a field to filter on |
| WARN | abnormal, must be monitored | a consumer job retried after an error |
| ERROR | broken, must be fixed | an action failed because a dependency failed |

## Pre-push check
- [ ] No `console.log`; no whole object or payload as fields; no secrets or personal data.
- [ ] Errors thrown with static message, `info` with all inputs, `cause`; no extra error log next to them.
- [ ] Context via logger fields / child logger, not context-only log lines.
- [ ] No duplicate of an automatic framework log; level matches the table.
