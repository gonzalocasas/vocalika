# Feature architecture

Vocalika is organized around projects. A project owns one prepared reference
and many takes; a take may own one analysis. Features communicate through
those persisted records and API contracts rather than importing one another's
implementation state.

## Dependency direction

```text
Vue app shell
  ├─ projects feature ───────┐
  ├─ reference feature ──────┤
  ├─ takes feature ──────────┼─ shared API client + domain types
  ├─ recording feature ──────┤
  ├─ compare feature ────────┤
  └─ export feature ─────────┘

FastAPI routers
  └─ project service
       ├─ project repository
       ├─ reference preparation
       ├─ export mixdown
       └─ existing analysis pipeline
            └─ audio / pitch / alignment primitives
```

Dependencies point inward. Domain records and service interfaces do not know
about FastAPI or Vue. The analysis pipeline does not know about projects. The
recording feature produces an ordinary audio upload and does not know how an
analysis is calculated.

## Backend boundaries

- `vocalika.projects.models`: serializable `Project`, `ProjectReference`, and
  `Take` records.
- `vocalika.projects.repository`: filesystem persistence and identifier/path
  validation. No audio processing.
- `vocalika.projects.service`: project preparation and take lifecycle. It is
  the only project feature allowed to invoke source acquisition, separation,
  or `run_analysis`.
- `vocalika.projects.export`: aligned take placement and instrumental mixdown.
  It consumes persisted project records and analysis timestamps without
  coupling the analysis pipeline to delivery formats.
- `vocalika.api.projects`: HTTP translation only. It validates multipart input,
  delegates work, and serves project-owned media/artifacts.
- `vocalika.api.uploads`: shared upload filename and size policy.

Project records are stored below `analysis-output/projects/<project-id>/`.
Reference and take media are copied into that directory so a cache clear does
not destroy the workspace. Expensive downloaded/separated intermediates may
still be reused from Vocalika's cache.

## Frontend boundaries

- `features/projects`: project library and project creation.
- `features/reference`: stem monitoring, trim, and reference settings.
- `features/takes`: take list, upload, and analysis actions.
- `features/recording`: microphone permission, `MediaRecorder`, and recording
  controls. Its output is a `File`, identical to a dropped upload.
- `features/compare`: metric cards, Plotly diagnostics, and listening gate.
- `features/export`: take selection, preview controls, and downloadable
  mixdown requests.
- `shared`: API client, persisted DTOs, and presentation-neutral utilities.

`App.vue` is an app-shell/router state machine only. It owns the selected
project and active tab, while each feature owns its local interaction state.

## Extension seams

- Additional export encoders can consume the rendered mix without changes to
  recording, comparison, or analysis.
- Transposition is a project setting and can be implemented as an alternate
  prepared-reference revision. Takes retain the revision used for analysis.
- Authentication or remote object storage can replace the repository/API
  adapters without changing the audio pipeline or Vue feature components.
