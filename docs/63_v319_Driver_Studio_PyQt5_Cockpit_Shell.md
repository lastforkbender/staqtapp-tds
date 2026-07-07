# v3.1.9 Driver Studio PyQt5 Cockpit Shell

TDS v3.1.9 introduces the first optional PyQt5 shell for Driver Studio. It is a cockpit layer over the existing Studio evidence and action backends, not a new trust authority.

## Design intent

The shell is intended to feel like the TDS Browser operations console:

- dark professional surface
- blue, purple, and orange telemetry accents
- custom SVG iconography rather than emoji or ASCII icons
- panel cockpit layout instead of dialogue-heavy workflows
- import-safe behavior when PyQt5 is not installed

The shell package is `staqtapp_tds.studio_pyqt5`.

## New modules

```text
staqtapp_tds/studio_pyqt5/
    __init__.py
    app.py
    availability.py
    bridge.py
    icons.py
    main_window.py
    theme.py
    panels/
        __init__.py
        descriptors.py
```

## Core objects

### `StudioQtBridge`

`StudioQtBridge` is the headless seam between the GUI and the Studio backend. It loads evidence bundles through `DriverStudioReadOnlyConsole`, converts snapshots into widget-neutral `StudioQtShellState`, and builds `StudioReviewActionRequest` objects for review buttons.

The bridge deliberately has no `approve`, `sign`, `activate`, or `execute` helpers.

### `StudioQtShellState`

`StudioQtShellState` is an immutable render payload for the shell. It contains:

- top-level status
- selected driver ID
- evidence bundle identifiers
- console hash
- panel view models
- event count
- shell capability matrix

### `StudioQtPanelViewModel`

Each panel view model combines a v3.1.7 panel snapshot with v3.1.9 shell metadata: title, icon name, dock area, surface type, action-button availability, rows, metrics, and warnings.

### `DriverStudioMainWindow`

`DriverStudioMainWindow` is the optional Qt window. Importing its module is safe without PyQt5, but constructing a real window requires PyQt5. This keeps the core TDS package usable in server, CI, and headless environments.

## Panels

The shell defines descriptors for:

- Driver Evidence Queue
- Evidence Bundle Viewer
- Audit Trail Panel
- Fixture Replay Summary
- Risk Card Inspector
- Registry State Observer
- Export Integrity Verifier
- Bottom Event Console

Only Driver Evidence Queue and Risk Card Inspector are marked as action-button surfaces, and those buttons submit requests through the v3.1.8 action layer rather than granting direct authority.

## Optional dependency

PyQt5 is not a required dependency. Install the optional GUI extra when a real desktop window is needed:

```bash
pip install .[gui]
```

Headless use remains available without PyQt5:

```python
from staqtapp_tds.studio_pyqt5 import StudioQtBridge

bridge = StudioQtBridge()
state = bridge.shell_state()
assert state.status == "empty"
```

## Authority boundary

The v3.1.9 shell can:

- render the cockpit
- render custom SVG iconography
- render read-only panels
- show action buttons
- submit review actions through the v3.1.8 action layer
- load evidence bundles
- verify export integrity

The shell cannot:

- approve a driver by itself
- reject or quarantine as direct authority
- call `DriverRegistry.approve` directly
- sign or attach signatures
- activate drivers
- execute the Driver VM
- edit TDDL or bytecode
- write storage
- execute arbitrary Python
- mutate Registry state
- store private keys
- bypass policy

## Trust path

```text
PyQt5 Studio Shell
   │ renders immutable snapshots
   │ submits admin intent only
   ▼
StudioQtBridge
   │
   ├─ DriverStudioReadOnlyConsole
   │      └─ Evidence bundle snapshots
   │
   └─ DriverStudioAdminReviewActions
          └─ DriverBatchReviewBoard / Registry authority gates
```

Storage still owns data. Driver VM owns bytecode execution. Runtime Manager owns trust/evidence gating. Foundry owns AI-safe proposal/testing. Registry owns approval/signature/activation trust. Studio observes trust and submits intent before Studio influences trust.
