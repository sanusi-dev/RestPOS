Before making any changes to `plan.md`, first review and update `features.md` to ensure that every feature currently implemented or introduced in the codebase is documented.

### `features.md` requirements

`features.md` should become a concise feature specification document.

- Remove any references to URY, ERPNext, or any other external system.
- Remove the introductory note that says the project is derived from URY or ERPNext.
- Keep the project scope section brief and include only the information required for agents and future contributors to understand the project.
- Rewrite all features as finalized decisions rather than brainstorming notes.
- Avoid implementation history, design discussions, and references to where a feature originated.
- The document should describe **what the system does**, not **how the design decisions were reached**.

### `plan.md` requirements

`plan.md` has become inconsistent and disorganized. Information is duplicated, scattered across sections, and mixed with content that belongs in other documents.

Refactor `plan.md` into a much simpler structure containing only the following sections:

1. Project overview
2. Application architecture
3. Build sequence (a high-level implementation roadmap)

Any information that already exists in `agents.md` should be removed from `plan.md`.

Review whether the following sections should remain in `plan.md`:

- Project overview
- Application architecture
- Cross-cutting UI conventions

If any of them would be better placed in `agents.md`, move them there. In particular, determine whether the cross-cutting UI conventions section is still necessary and justify keeping or removing it.

### Build sequence structure

The build sequence should be presented as a table with the following columns:

| Column | Description |
| --- | --- |
| Phase | Development phase |
| Apps involved | Django apps affected |
| Features covered | Related entries from `features.md` |
| Completed work | Brief summary of what has already been implemented |
| Remaining work | Brief summary of what still needs to be be implemented |
| Detailed plan status | What has and has not been formally planned |
| Progress status | `Completed`, `Planned`, or `Under implementation` |

### New implementation workflow

The project is no longer attempting to replicate URY or ERPNext.

Those systems should now be treated only as reference material.

Going forward, the workflow for implementing new features should be:

1. Review how URY, ERPNext, and other comparable systems approach the feature.
2. Research current industry practices.
3. Consider the model's knowledge and the developer's requirements.
4. Propose an implementation plan.
5. Review the proposal with the developer through an iterative discussion process.
6. Produce a final, agreed-upon implementation plan.
7. Add only that final plan to the documentation.

### Detailed implementation plans

Detailed implementation plans require a complete rewrite.

They should no longer contain unnecessary contextual information such as:

- "This approach follows ERPNext."
- "This implementation is based on URY."
- References to Toast, ERP systems, or other products.
- Historical design discussions.
- Decision-making commentary.

The detailed plan should contain only the finalized implementation decisions that will be used during development.

The documentation should be treated as production documentation, not as a design notebook.
Also, get rid of that implementation history, after this rewrite we should a less bulky version of plan.md so that we dont need to abstract away some contents