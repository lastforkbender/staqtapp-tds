from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "eaglegate-capture-attestation.yml"


def test_capture_attestation_workflow_is_cross_platform_non_executing_and_gated():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Staqtapp-TDS Eaglegate capture witness attestation" in source
    assert "agent/eaglegate-offline-capability-capture" in source
    assert "agent/eaglegate-capture-witness-receipts" in source
    assert "ubuntu-24.04" in source
    assert "macos-14" in source
    assert "windows-2022" in source
    assert "python: '3.10'" in source
    assert "python: '3.13'" in source
    assert "tests/test_v380_eaglegate_capture_attestation.py" in source
    assert "tests/test_v380_eaglegate_capture_attestation_workflow_contract.py" in source
    assert "tests/test_v380_eaglegate_offline_capture.py" in source
    assert "tests/test_v380_eaglegate_vllm_shadow.py" in source
    assert "tests/test_v380_eaglegate_adapter_conformance.py" in source
    assert "tests/test_v380_eaglegate_exactness_laboratory.py" in source
    assert "tests/test_v380_eaglegate_lossless_foundation.py" in source
    assert "tests/test_install_contract.py" in source
    assert "python -m staqtapp_tds.eaglegate.capture_attestation_suite --json" in source
    assert "cmp attestation-a.json attestation-b.json" in source
    assert "cryptographic_signature_verified" in source
    assert "witness_independence_proven" in source
    assert "metadata_truth_claimed" in source
    assert "activation_authority" in source
    assert "real_runtime_qualified" in source
    assert "forbidden runtime or crypto imports" in source
    assert "Eaglegate capture attestation gates complete" in source
    assert 'test "$ATTESTATION_RESULT" = "success"' in source
