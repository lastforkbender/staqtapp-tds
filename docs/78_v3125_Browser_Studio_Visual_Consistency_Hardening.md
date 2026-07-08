# v3.1.25 Browser & Studio Visual Consistency Hardening

TDS v3.1.25 is a GUI visual-quality hardening release before the next persistence/edit-safety reliability layer.

## Browser hardening

The Browser dashboard now applies final-order visual QA rules that keep compact and desktop renders consistent after earlier responsive rules are overridden by later dashboard polish blocks.

The hardening focuses on:

- sidebar control-plane card containment
- long navigation list scroll safety
- compact desktop grid breakpoints
- workload donut/legend width pressure
- hero-orbit containment
- architecture connector rail containment
- panel text wrapping and minimum-width behavior

## README visual preview

The 1280×800 Browser telemetry overview screenshot is included at:

```text
docs/screenshots/tds_browser_telemetry_overview_1280x800.png
```

The root README embeds this image near the top so GitHub renders the Browser telemetry overview without requiring the long full-page screenshot to be opened separately.

## Studio hardening

The optional PyQt5 Driver Studio shell keeps the same authority boundary. The update improves visual consistency only:

- 1280×800 minimum window support
- dock nesting/tabbing options
- stronger dock and panel minimum sizes
- readable group box, field help, and text edit styling
- bounded Manual Builder scroll/split sizing
- clearer text-edit padding and selection styling

Studio remains an observe, hydrate, explain, verify, review-context, export-preparation, and intent-preparation cockpit. It does not approve, reject, quarantine, sign, activate, mutate Registry trust state, write storage, store private keys, execute trusted drivers, or bypass Runtime Manager / Foundry / Review Board / Registry policy.
