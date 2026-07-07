# v3.1.12 Driver Studio Live Cockpit Event Bridge

v3.1.12 adds a pure-Python live event bridge for the optional Driver Studio PyQt5 cockpit. The bridge sits above the v3.1.11 hydration layer and gives a real GUI a safe way to refresh panels, coordinate selected context, and consume bounded event updates.

```text
Backend truth
  ↓
StudioQtBridge
  ↓
StudioCockpitHydrator
  ↓
StudioCockpitEventBridge
  ↓
PyQt5 polling/signals/widgets
```

The live bridge is still not a trust authority. It records UI-facing events and returns immutable hydrated snapshots. Runtime Manager, Review Board, Registry, Foundry, Driver VM, and storage keep their existing responsibilities.

## New live bridge models

```text
StudioCockpitEventBridge
StudioLiveCockpitState
StudioLiveEvent
StudioLiveEventKind
StudioCockpitSelection
StudioPanelRefreshContract
```

## Events

The bounded stream records cockpit events such as:

```text
bundle_loaded
driver_selected
panel_refreshed
snapshot_refresh
review_action_submitted
manual_proposal_previewed
manual_proposal_submitted
```

Events are intentionally UI-facing and bounded. If the buffer is full, older events fall out of the in-memory stream; the bridge does not write storage.

## Refresh contracts

`studio_panel_refresh_contracts()` returns stable refresh metadata for every Studio panel. For example:

```text
Driver Evidence Queue        snapshot
Risk Card Inspector          selected_snapshot
Bottom Event Console         bounded_append_stream
Manual Driver Builder        form_state / proposal_only
Export Integrity Verifier    hash_snapshot
```

These contracts tell the GUI how to update. They do not grant mutation authority.

## Signal payloads

`StudioLiveCockpitState.signal_payload()` returns JSON-friendly metadata for Qt signal emission:

```text
generation
cursor
status
severity
selected_driver_id
bundle_id
bundle_hash
console_hash
event_count
latest_event_id
panel_status
capability_matrix
```

A PyQt5 application can poll this payload or emit it from a timer/signal bridge without exposing backend objects to widgets.

## Authority boundary

The live bridge may:

```text
render hydrated snapshots
coordinate selected driver/bundle state
emit bounded UI events
produce Qt-signal-friendly payloads
route review intent through StudioQtBridge
route manual proposals through Foundry
```

The live bridge must not:

```text
approve drivers
sign drivers
activate drivers
mutate Registry state
write storage
execute Driver VM authority paths
store private keys
bypass Runtime Manager policy
bypass Foundry validation
```

This keeps Driver Studio live and responsive without turning the cockpit into a trust root.
