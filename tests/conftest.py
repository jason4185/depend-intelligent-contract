import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "Depend.py"
ALICE = "0x" + "11" * 20
BOB = "0x" + "22" * 20
CHARLIE = "0x" + "33" * 20
BASE_TIME = "2026-01-01T00:00:00Z"


class ContractError(Exception):
    pass


class ConsensusError(Exception):
    pass


class Address:
    def __init__(self, value):
        self.as_hex = value


class Return:
    def __init__(self, calldata):
        self.calldata = calldata


class TrackedRaw(dict):
    def __init__(self, vm, *args, **kwargs):
        self.vm = vm
        super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        if self.vm.in_nondet and key == "datetime":
            self.vm.time_reads_in_nondet += 1
        return super().__getitem__(key)

    def get(self, key, default=None):
        if self.vm.in_nondet and key == "datetime":
            self.vm.time_reads_in_nondet += 1
        return super().get(key, default)


class TrackedMessage:
    def __init__(self, vm):
        self.vm = vm
        self.sender_address = ALICE
        self.raw = TrackedRaw(vm, {"datetime": BASE_TIME})

    def __getattribute__(self, name):
        if name == "sender_address":
            vm = object.__getattribute__(self, "vm")
            if vm.in_nondet:
                vm.sender_reads_in_nondet += 1
        return object.__getattribute__(self, name)


class FakeTreeMap(dict):
    def __init__(self, vm):
        self.vm = vm
        super().__init__()

    @classmethod
    def __class_getitem__(cls, item):
        return cls

    def get(self, key, default=None):
        if self.vm.in_nondet:
            self.vm.storage_reads_in_nondet += 1
        return super().get(key, default)

    def __getitem__(self, key):
        if self.vm.in_nondet:
            self.vm.storage_reads_in_nondet += 1
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if self.vm.in_nondet:
            self.vm.storage_writes_in_nondet += 1
        return super().__setitem__(key, value)


class FakeLLM:
    def __init__(self):
        self.responses = []
        self.calls = []

    def set_responses(self, *responses):
        self.responses = list(responses)

    def exec_prompt(self, prompt, response_format=None):
        self.calls.append((prompt, response_format))
        if not self.responses:
            raise AssertionError("LLM response queue is empty")
        return self.responses.pop(0)


class Public:
    @staticmethod
    def view(fn):
        return fn

    class _Write:
        def __call__(self, fn):
            return fn

    write = _Write()


class FakeVM:
    UserError = ContractError
    Return = Return

    def __init__(self, llm):
        self.llm = llm
        self.in_nondet = False
        self.storage_reads_in_nondet = 0
        self.storage_writes_in_nondet = 0
        self.sender_reads_in_nondet = 0
        self.time_reads_in_nondet = 0
        self.run_count = 0

    def run_nondet(self, leader_fn, validator_fn):
        self.run_count += 1
        self.in_nondet = True
        try:
            proposal = leader_fn()
        finally:
            self.in_nondet = False
        leader_result = Return(proposal)
        self.in_nondet = True
        try:
            accepted = validator_fn(leader_result)
        finally:
            self.in_nondet = False
        if not accepted:
            raise ConsensusError("proposal mismatch")
        return proposal


class Harness:
    def __init__(self):
        self.llm = FakeLLM()
        self.vm = FakeVM(self.llm)
        self.message = TrackedMessage(self.vm)
        self.module = self._load_contract_module()
        self.gl = self.module.gl
        self.contract = self.module.Depend()
        for field in (
            "workflow_records", "task_records", "task_slot_index", "graph_records",
            "dependency_records", "latest_workflow_by_owner", "latest_task_by_submitter",
        ):
            setattr(self.contract, field, FakeTreeMap(self.vm))

    def _load_contract_module(self):
        fake_genlayer = types.ModuleType("genlayer")
        fake_storage = types.ModuleType("genlayer.storage")
        fake_storage.TreeMap = FakeTreeMap
        fake_types = types.ModuleType("genlayer.types")
        fake_types.u256 = int
        fake_types.Address = Address
        fake_types.__all__ = ["u256", "Address"]
        fake_genlayer.public = Public
        fake_genlayer.vm = self.vm
        fake_genlayer.nondet = types.SimpleNamespace(exec_prompt=self.llm.exec_prompt)
        fake_genlayer.message = self.message
        fake_genlayer.storage = fake_storage
        fake_genlayer.types = fake_types
        fake_genlayer.contract = types.SimpleNamespace(Contract=type("Contract", (), {}))
        spec = importlib.util.spec_from_file_location("depend_test_module", CONTRACT)
        module = importlib.util.module_from_spec(spec)
        previous = {
            "genlayer": sys.modules.get("genlayer"),
            "genlayer.storage": sys.modules.get("genlayer.storage"),
            "genlayer.types": sys.modules.get("genlayer.types"),
        }
        sys.modules["genlayer"] = fake_genlayer
        sys.modules["genlayer.storage"] = fake_storage
        sys.modules["genlayer.types"] = fake_types
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        finally:
            for name, old in previous.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old
        return module

    def set_sender(self, sender):
        self.message.sender_address = sender

    def set_raw(self, leader_item, validator_item=None):
        self.llm.set_responses(
            leader_item, leader_item if validator_item is None else validator_item
        )

    def create(self, name="Operations", policy="A task is a prerequisite only when it must finish before another can begin."):
        self.set_sender(ALICE)
        return self.contract.create_workflow(name, policy)

    def submit(self, workflow_id, key, text, sender=BOB):
        self.set_sender(sender)
        return self.contract.submit_task(workflow_id, key, text)

    def seal(self, workflow_id, sender=ALICE):
        self.set_sender(sender)
        return self.contract.seal_workflow(workflow_id)

    def map(self, workflow_id, result, validator_result=None, sender=ALICE):
        self.set_sender(sender)
        self.set_raw(result, validator_result)
        return self.contract.map_dependencies(workflow_id)

    def complete(self, workflow_id, task_id, sender=ALICE):
        self.set_sender(sender)
        return self.contract.complete_task(workflow_id, task_id)


@pytest.fixture
def env():
    return Harness()


def expect_error(call, message=None):
    with pytest.raises((ContractError, ConsensusError)) as error:
        call()
    if message is not None:
        assert message in str(error.value)
    return error.value


def stored(contract, store_name, identifier):
    return json.loads(getattr(contract, store_name)[identifier])
