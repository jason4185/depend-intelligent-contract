import json
import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("DEPEND_NATIVE_TESTS") != "1",
    reason="native genlayer-test plugin is not available in the default local run",
)


def test_direct_dependency_flow(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/Depend.py")
    direct_vm.sender = direct_alice
    workflow_id = contract.create_workflow(
        "Release workflow",
        "A task is a prerequisite only when it must finish before another can begin.",
    )
    direct_vm.sender = direct_bob
    task_a = contract.submit_task(workflow_id, "schema", "Deploy the new database schema.")
    task_b = contract.submit_task(workflow_id, "validate", "Run migration validation against the new schema.")
    direct_vm.sender = direct_alice
    contract.seal_workflow(workflow_id)
    direct_vm.mock_llm(
        r"DEPEND V1 semantic evaluator",
        json.dumps({
            "status": "MAPPED",
            "dependencies": [
                {"task_id": task_a, "requires": []},
                {"task_id": task_b, "requires": [task_a]},
            ],
        }),
    )
    contract.map_dependencies(workflow_id)
    assert contract.get_ready_mask(workflow_id) == 1
    contract.complete_task(workflow_id, task_a)
    assert contract.get_ready_mask(workflow_id) == 2

