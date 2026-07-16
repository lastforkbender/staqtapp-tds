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

The former telemetry overview image was retired during v3.5.3 release qualification because a single Dashboard capture could not truthfully demonstrate every Browser page. The current evidence is a set of 19 distinct 1280×800 captures under:

```text
docs/screenshots/browser_pages/
```

The root README embeds every image vertically in navigation order. The reproducible capture driver selects and validates each page before taking its screenshot, including the real CSV Interpole Monitor as page 07.

## Studio hardening

The optional PyQt5 Driver Studio shell keeps the same authority boundary. The update improves visual consistency only:

- 1280×800 minimum window support
- dock nesting/tabbing options
- stronger dock and panel minimum sizes
- readable group box, field help, and text edit styling
- bounded Manual Builder scroll/split sizing
- clearer text-edit padding and selection styling

Studio remains an observe, hydrate, explain, verify, review-context, export-preparation, and intent-preparation cockpit. It does not approve, reject, quarantine, sign, activate, mutate Registry trust state, write storage, store private keys, execute trusted drivers, or bypass Runtime Manager / Foundry / Review Board / Registry policy.
