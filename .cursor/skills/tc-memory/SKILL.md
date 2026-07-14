# Tc Chat Memory Protocol

You (a Tc Chat Agent) have a layered long-term memory. **Memory is only useful when read, and stays healthy only when written sparingly.** This skill is the operating manual: when to read, when to write, which tool, and the scope/size discipline that keeps memory lean.

## 1. The layers (+ runtime state)

| Layer | What it holds | Bound to | Size limit | Read / Write |
|---|---|---|---|---|
| Profile | User long-term preferences / conventions / universal tastes (communication, tech taste, habits, taboos) | User (global, all projects) | concise | `profile_read` / `profile_write` |
| Soul | General coding style (naming / comments / error handling / testing / architecture taste) | User (global) | concise | `soul_read` / `soul_write` |
| **Role Portrait** | **This role's** self-portrait + working preferences ("who I am / how I work") | Role (global, by role name) | **Capped (default 2000 chars, configurable)** | `role_memory_read` / `role_memory_write` |
| **Role Experience** | **This role's** reusable playbooks / lessons learned **in the current project** | Role + Project | soft | `role_experience_read` / `role_experience_write` |
| Knowledge Graph (KG) | **The project's** knowledge / decisions / relations | Project | per-node | `kg_search` / `kg_get_subgraph` / `kg_upsert_entity` / `kg_link` |

> Runtime state (`share_context` / `get_team_context`, autopilot) is NOT memory — **never write it into a memory layer**.

**Boundary mnemonic**: **user (cross-project preferences/conventions)** → Profile · **how to write code** → Soul · **who this role is** → Role Portrait · **what this role learned in THIS project** → Role Experience · **the project's facts/decisions/relations** → KG.

**Portrait vs Experience (the key split).** The Portrait is a SHORT, stable identity (capped, cross-project). Concrete, accumulating lessons are EXPERIENCE and live OUTSIDE the portrait, in `role_experience` — **bound to this role, scoped to the current project**. Keeping experience out of the portrait is exactly what keeps the portrait under its limit.

**There is NO global role-experience.** Experience is **project-level only**. Anything truly cross-project and universal is a *user preference/convention* → it belongs in the **Profile** (coding style → Soul). So: global ⇒ Profile; per-role-per-project ⇒ Role Experience.

## 2. When to READ — iron rule

**On every task, before acting**, run the memory startup self-check (in order, none skipped):

1. `profile_read()` — align with the user's cross-project preferences/conventions
2. `soul_read()` — align coding style before writing code (skippable for pure analysis / lookup)
3. `role_memory_read({ roleName, sessionId })` — load this role's **Portrait** (identity + how it works). roleName = the `【】` prefix of your sessionId (e.g. `【资深全栈架构师】` → `资深全栈架构师`), **verbatim, no translation/abbreviation**; always pass sessionId so the server canonicalizes via the active-sessions registry (anti-fragmentation)
4. `role_experience_read({ roleName, sessionId })` — load this role's **experience for the current project** (lessons it already learned here)
5. `kg_search({ query: "<task keywords>" })` — recall the project's knowledge / decisions / relations (lexical multi-term scoring; **space-separate terms** to boost recall); on hits, expand with `kg_get_subgraph`

Only one-line small talk / trivial Q&A may skip.

## 3. When to WRITE — sparingly, to the right layer

On finishing a task, self-check: "did I learn something **stable & reusable**?" If yes, persist to the matching layer:

- Stable user preference / convention (cross-project, universal) → `profile_write`
- General coding style → `soul_write`
- A change to **who this role is / how it works** → `role_memory_write` (Portrait — keep it short; see §4 cap)
- A reusable **lesson / playbook this role learned in this project** → `role_experience_write` (project-level, by role)
- The project's knowledge / decisions / module relations → `kg_upsert_entity` (+ `kg_link` for relations)
- Outdated / superseded knowledge → `kg_upsert_entity({ status:"deprecated" })` or a `supersedes` edge (new -[supersedes]-> old, auto-deprecates old); search returns only the latest by default

**Persist only stable, reusable items**; never write one-off, transient, or volatile info.

## 4. Portrait char limit & self-summarization (mandatory)

The Role Portrait is **capped** — default **2000 characters** (counted by Unicode code points, so Chinese = 2000 字). Configurable in the memory page UI or `~/.tc-chat/global/memory-config.json` → `portraitMaxChars` (range 200–50000).

- `role_memory_write` **rejects** any content over the limit with `OVER_LIMIT (current/max)` — nothing is saved.
- On `OVER_LIMIT`: **(1)** `role_memory_read` the current portrait; **(2) summarize / distill** to ≤ limit (keep only stable "who I am / how I work"); **(3) move concrete experience OUT** → `role_experience_write` (this role, current project); cross-project universal preferences → `profile_write`; **(4)** `role_memory_write` again.
- Be proactive: when the portrait nears the limit, summarize before it overflows.

## 5. Write discipline (mandatory)

1. **Read before write.** Profile / Soul / Role Portrait / Role Experience are **full-overwrite**. Always `*_read` first, append/revise the relevant section, then `*_write` — **never overwrite blindly** (it wipes user-edited content). KG's `kg_upsert_entity` auto-appends + dedups, so it is relatively safe.
2. **Concise & bounded.** Memory is a high-signal summary, not a log; keep it short.
3. **Right layer.** Don't write project specifics into the global Profile/Soul/Portrait; don't put cross-project universal preferences into per-project Role Experience.

## 6. Examples

✅ User says "always reply in Chinese, keep it short" → `profile_read` → append under communication-preferences → `profile_write` (cross-project, universal).
✅ A debugging trick worked **in this project** → `role_experience_read` → append the lesson → `role_experience_write` (project, by role).
✅ Portrait write returns `OVER_LIMIT` → read → distill identity to ≤ limit, push details into Role Experience → write again.
✅ A reusable project fact / decision / module relation → `kg_upsert_entity` (+ `kg_link`).

❌ Finishing a task and wrapping up without judging whether to persist.
❌ Cramming concrete experience into the Portrait until it overflows (it belongs in `role_experience`).
❌ `role_memory_write` / `role_experience_write` with new content without reading first → wipes history.
❌ Putting a one-project lesson into the global Profile, or a cross-project universal preference into per-project Role Experience.
