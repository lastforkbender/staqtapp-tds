from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "eaglegate-shadow-attestation.yml"


def test_attestation_workflow_is_cross_platform_and_aggregate_gated():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Staqtapp-TDS Eaglegate shadow attestation" in source
    assert "agent/eaglegate-shadow-sdk" in source
    assert "agent/eaglegate-shadow-attestation" in source
    assert "ubuntu-24.04" in source
    assert "macos-14" in source
    assert "windows-2022" in source
    assert "python: '3.10'" in source
    assert "python: '3.13'" in source
    assert "tests/test_v380_eaglegate_shadow_attestation.py" in source
    assert "tests/test_v380_eaglegate_attestation_workflow_contract.py" in source
    assert "tests/test_v380_eaglegate_shadow_sdk.py" in source
    assert "tests/test_v380_eaglegate_adapter_conformance.py" in source
    assert "tests/test_v380_eaglegate_exactness_laboratory.py" in source
    assert "tests/test_v380_eaglegate_lossless_foundation.py" in source
    assert "tests/test_install_contract.py" in source
    assert "python -m staqtapp_tds.eaglegate.attestation reference --json" in source
    assert "attestation-a.json" in source
    assert "attestation-b.json" in source
    assert "cryptographic_signature_verified" in source
    assert "witness_independence_proven" in source
    assert "metadata_truth_claimed" in source
    assert "Eaglegate shadow attestation gates complete" in source
    assert 'test "$ATTESTATION_RESULT" = "success"' in source
