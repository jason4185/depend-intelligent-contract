import ast
from pathlib import Path


SOURCE_PATH = Path(__file__).resolve().parents[1] / "contracts" / "Depend.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE_MAPS = {
    "workflow_records": "TreeMap[str, str]",
    "task_records": "TreeMap[str, str]",
    "task_slot_index": "TreeMap[str, str]",
    "graph_records": "TreeMap[str, str]",
    "dependency_records": "TreeMap[str, str]",
    "latest_workflow_by_owner": "TreeMap[str, str]",
    "latest_task_by_submitter": "TreeMap[str, str]",
}


def contract_class():
    tree = ast.parse(SOURCE)
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Depend")


def public_methods(decorator_name):
    methods = []
    for node in contract_class().body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if ast.unparse(decorator) == "gl.public." + decorator_name:
                methods.append(node)
    return methods


def test_runtime_pin_source_size_and_storage_shape():
    assert SOURCE.startswith(
        '# v0.3.0\n# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }'
    )
    assert len(SOURCE.encode("utf-8")) < 52000
    assert "DynRay" not in SOURCE
    assert "DynArray" not in SOURCE
    assert "run_nondet_unsafe" not in SOURCE
    assert "@gl.public.write.payable" not in SOURCE
    assert "gl.message.value" not in SOURCE
    assert "emit_transfer" not in SOURCE
    assert "http" not in SOURCE.lower()
    assert "requests" not in SOURCE.lower()

    annotations = {
        node.target.id: ast.unparse(node.annotation)
        for node in contract_class().body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert {key: annotations[key] for key in TREE_MAPS} == TREE_MAPS
    assert sum(value == "u256" for value in annotations.values()) == 3
    assert len([value for value in annotations.values() if value.startswith("TreeMap")]) == 7


def test_exact_public_abi_and_constructor():
    assert {node.name for node in public_methods("write")} == {
        "create_workflow", "submit_task", "seal_workflow", "map_dependencies", "complete_task"
    }
    assert {node.name for node in public_methods("view")} == {
        "get_workflow", "get_workflow_status", "get_task", "get_task_id", "get_graph",
        "get_dependency", "get_prerequisite_mask", "get_ready_mask", "is_task_ready",
        "get_latest_workflow_for_owner", "get_my_latest_workflow",
        "get_latest_task_by_submitter", "get_my_latest_task",
    }
    constructor = next(
        node for node in contract_class().body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    assert len(constructor.args.args) == 1


def test_only_semantic_path_calls_prompt_and_consensus():
    tree = ast.parse(SOURCE)
    prompt_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "gl.nondet.exec_prompt"
    ]
    assert len(prompt_calls) == 1
    semantic_result = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_semantic_result")
    assert any(isinstance(node, ast.Call) and ast.unparse(node.func) == "gl.nondet.exec_prompt" for node in ast.walk(semantic_result))
    consensus = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_semantic_consensus")
    assert any(isinstance(node, ast.Call) and ast.unparse(node.func) == "gl.vm.run_nondet" for node in ast.walk(consensus))
    source = ast.get_source_segment(SOURCE, consensus)
    assert source is not None
    for forbidden in ("workflow_records", "task_records", "sender_address", "datetime"):
        assert forbidden not in source


def test_all_task_iteration_constants_are_bounded():
    taskish = ("tasks", "entries", "dependencies", "requires", "masks", "closure_entries", "dependency_records")
    for line in SOURCE.splitlines():
        if line.lstrip().startswith("for ") and any(word in line for word in taskish):
            assert "MAX_TASKS" in line or "len(" in line
