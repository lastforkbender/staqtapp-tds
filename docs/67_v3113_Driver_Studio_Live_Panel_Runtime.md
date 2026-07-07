# v3.1.13 Driver Studio Live Panel Runtime

v3.1.13 adds a pure-Python live panel runtime for the optional Driver Studio PyQt5 cockpit. The runtime sits above the v3.1.12 live event bridge and turns bounded retained events into deterministic dirty-panel marks and Qt-ready refresh packets.

The runtime is a GUI coordination layer. It does not approve, sign, activate, execute trusted drivers, mutate Registry state, write storage, store private keys, or bypass policy.

## New module

```text
staqtapp_tds.studio_pyqt5.runtime
```

## New public objects

```text
StudioLivePanelRuntime
StudioPanelRuntimeState
StudioPanelDirtyMark
StudioPanelRefreshPacket
studio_live_panel_runtime_capability_matrix()
```

## Bridge addition

```python
bridge.live_panel_runtime(max_events=256)
```

## Flow

```text
StudioCockpitEventBridge
   │ retained live events
   ▼
StudioLivePanelRuntime
   │ event-to-panel routing through StudioPanelRefreshContract
   ▼
StudioPanelDirtyMark
   │ one or more reasons per affected panel
   ▼
StudioPanelRefreshPacket
   │ immutable Qt-ready hydrated panel payload
   ▼
PyQt5 tables / cards / timelines / form views
```

## What the runtime coordinates

```text
bundle loaded              -> queue, evidence bundle, audit, fixture, registry, export, event console
selected driver changed    -> fixture, risk card, registry, event console
review action submitted    -> audit, risk card, event console
manual proposal previewed  -> manual builder, event console
manual proposal submitted  -> manual builder, event console
snapshot refreshed         -> snapshot-based panels and event console
panel refreshed            -> event console feed coordination
```

## Why this matters

The v3.1.11 hydration layer made panels renderable. The v3.1.12 live bridge made events streamable. v3.1.13 connects those two pieces so a future PyQt5 main window can update only the panels affected by each event.

This is important for the future export/audit console path: export integrity, audit history, evidence cards, and bottom event-console streams can now be refreshed coherently without giving the Studio write authority.

## Authority boundary

The runtime may:

```text
track dirty panels
consume incremental events
create panel refresh packets
emit Qt-friendly signal payloads
coordinate selected driver/bundle context
hydrate immutable snapshots
```

The runtime must not:

```text
approve drivers
sign drivers
activate drivers
mutate Registry trust state
write storage
store private keys
execute trusted drivers directly
bypass Runtime Manager policy
bypass Foundry validation
bypass Review Board authority
bypass Registry approval/signature/activation trust
```
