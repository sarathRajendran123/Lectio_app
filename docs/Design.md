# Design system and UX standards

The interface is a Streamlit app (`frontend/`). The style is deliberately simple and quiet: light paper background, one teal accent, plain sans-serif, large readable type. A dark "Console" redesign with a light/dark switch was built and evaluated; it was set aside in favour of this plainer look (see `Memory.md`).

## Principles
1. **The lecturer decides.** Every generated item is labelled a suggestion; approve, edit and reject are always visible and nothing is applied silently.
2. **Say why.** A score without data is "Not assessable" with the reason, never "Unknown" and never 0%. A projected score is labelled as a projection next to the verified one.
3. **Show the evidence.** Findings link to the exact excerpt, document, page or slide. Citations show the quoted text.
4. **Plain language.** No jargon in labels; German and English content are both displayed as written.
5. **Calm density.** One idea per section, generous spacing, no decoration.

## Visual language (from `frontend/app.py` and `.streamlit/config.toml`)
| Token | Value | Use |
|---|---|---|
| Ink | `#182B3A` | text, headings |
| Accent | `#24695D` (teal) | primary buttons, selected state |
| Page background | `#FAF9F6` | main area |
| Sidebar | `#EDF1EF`, border `#DCE3DF` | navigation |
| Card | white, border `#DEE4E0`, radius 12 px | metrics, expanders |
| Focus ring | 3 px `#B87928` | keyboard focus on buttons and inputs |

## Type scale
Root size 112.5% (18 px). Headings: h1 2.5 rem, h2 1.9 rem, h3 1.45 rem. Captions 0.95 rem, widget labels 1 rem, metric values 2.4 rem. On screens narrower than 700 px the root steps down to 106%.

## Layout
- Wide layout, content max width 1440 px, sidebar at least 270 px.
- Sidebar: product name, user and role, page list, logout. Pages in order: Dashboard, Documents & upload, Course workbench, Course Structure, Knowledge Graph, Alignment Reports, Generated Content, Approval Center, Analytics, System status, Admin Panel (admins and department heads).
- Navigation between pages keeps selection in session state; quick actions can redirect.

## Components and states
| Component | Behaviour |
|---|---|
| Score card | `st.metric` with the verified score and status; projected score card beneath when approved drafts exist |
| Findings | severity, plain description, suggested action, evidence excerpt, decision form |
| Draft card | title, type, Bloom level, evidence heuristic, status; expander with full text and citations |
| Approval actions | Approve, Edit draft, Reject (reason required); decisions and revisions are kept |
| Document list | name, type, status, size; chunk, page, slide and word counts; two-step delete |
| Progress | audit and ingestion poll the API; steps show agent, status, tokens, duration |

**Four states for every data region:** loading (spinner), empty (what belongs here and where to add it), error (what failed, shown from the API message), full. Confirmation for destructive actions is two clicks.

## Accessibility
- Visible keyboard focus on all controls.
- Meaning is never colour alone: statuses are words ("WARNING", "needs review").
- Text sizes are large by default; contrast follows Streamlit's light theme with the palette above.
- Tables and expanders are native Streamlit elements, so screen readers get standard semantics.
- Not audited with a screen reader or against a formal WCAG checklist.

## Content rules
- Never invent figures, quotes or sources.
- Heuristic scores carry a notice: "heuristic evidence indicators, not probabilities".
- Missing material is "insufficient evidence", not proof of an error.

## Responsive behaviour
Streamlit stacks columns on narrow screens and collapses the sidebar; headings and root size reduce under 700 px. Screenshots of the current UI are in `docs/screenshots/`.
