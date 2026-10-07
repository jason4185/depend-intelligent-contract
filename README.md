# DEPEND

DEPEND is a reusable GenLayer semantic dependency-graph primitive. Its core question is: **what depends on what?** A bounded natural-language task set is sealed, GenLayer derives prerequisites, and deterministic code normalizes the result into a canonical transitive-closure graph whose masks control readiness and completion.

DEPEND models a partial order, not a total ranking. Independent tasks can be ready at the same time.

## Why GenLayer

Deterministic code handles ownership, bounds, slots, replay protection, sealing, graph normalization, transitive closure, cycle rejection, bitmasks, readiness, completion, digests, and persistence.

GenLayer handles the semantic question that generic deterministic code cannot answer: which natural-language tasks are genuine prerequisites of other tasks under the submitted dependency policy? That graph is consensus-critical because it directly controls which future `complete_task` calls are allowed. DEPEND does not execute the tasks or verify real-world work.

## Who can use it

The primitive is domain-neutral. It can support AI agents, software releases, DAO plans, business processes, incident response, research, approvals, multi-agent coordination, or project management. None is hardcoded.

## How it works

An owner creates a workflow with a name and policy. While `OPEN`, any address may submit a task with a key and text. Each task receives a deterministic ID, submitter, contiguous slot, and task digest. Reusing the same workflow, submitter, and task key is rejected; the same key is allowed for another submitter or workflow.

At least two tasks are required to seal and at most six may exist. `get_task_id(workflow_id, slot)` provides bounded slot discovery.

## Lifecycle

Lifecycle:

```text
OPEN -> SEALED -> MAPPED -> ACTIVE -> COMPLETED
```

`OPEN` accepts submissions. The owner calls `seal_workflow` once the task count is valid; sealing freezes submissions and commits the exact ordered task set in `task_set_digest`. `MAPPED` means an immutable dependency graph has been finalized. The first successful completion changes the workflow to `ACTIVE`; subsequent completions leave it active until every task is complete. `COMPLETED` is terminal.

If semantic mapping cannot produce a coherent acyclic graph, consensus may finalize the workflow as `UNRESOLVED`. That status is terminal, has no dependency records, and cannot be remapped or completed.

## Semantic consensus

`map_dependencies` is the only write that performs GenLayer semantic judgment. It snapshots the workflow configuration, sealed task-set commitment, and every task before entering:

```python
gl.vm.run_nondet(leader_fn, validator_fn)
```

The leader and validator independently evaluate the same policy and sealed task data. Results are parsed and normalized before exact canonical comparison. Storage, sender, and transaction-time access are outside those closures.

The evaluator accepts only `MAPPED` or `UNRESOLVED`. A prerequisite means one task **must** be completed before another can validly begin. Importance, preference, chronology, convenience, and mere relation do not create dependencies. Policy and task text are untrusted data, not model instructions. Evaluation does not browse, fetch URLs, consult an oracle, or verify external facts.

## Canonical graph and readiness

For `MAPPED`, every sealed task must appear exactly once. Unknown, invented, cross-workflow, duplicate, self-referential, or otherwise malformed prerequisites are rejected. Raw prerequisite edges become slot-based bitmasks, then bounded transitive closure is computed. Thus, if A is required by B and B is required by C, C’s canonical mask contains both A and B. A direct redundant edge A-to-C produces the same canonical closure.

The graph must be acyclic; self-dependencies and cycles fail validation. The stored graph is immutable after mapping.

Tasks occupy slots 1 through 6. Slot 1 maps to bit 0, slot 2 to bit 1, and slot 6 to bit 5. Each task has a canonical prerequisite mask, while the workflow stores `completed_mask`. A task is ready only in `MAPPED` or `ACTIVE`, is not already complete, and has every prerequisite bit set in `completed_mask`. `get_ready_mask` returns all ready tasks, and `is_task_ready` checks one task. There is no single canonical next task: independent tasks may be ready simultaneously.

## Completion and trust model

`complete_task` is deterministic and owner-controlled. It verifies the lifecycle state and workflow binding, reloads the task and dependency record, recomputes readiness from the stored masks, rejects blocked or already-completed tasks, and sets exactly one completion bit. A first completion changes `MAPPED` to `ACTIVE`; the final completion changes the workflow to `COMPLETED`.

The owner’s call is an onchain attestation of completion. DEPEND does not independently establish that work happened in the outside world.

## Digests and storage

Domain-separated SHA-256 digests bind workflow configuration, immutable tasks, the ordered sealed set, canonical closure, graph context, dependency records, and current records. `workflow_digest` excludes mutable progress. The finalized graph is bound to the workflow digest, task-set digest, semantic status, and closure digest, so completion does not alter the graph or graph digest.

Persistent storage uses seven `TreeMap`s: `workflow_records`, `task_records`, `task_slot_index`, `graph_records`, `dependency_records`, `latest_workflow_by_owner`, and `latest_task_by_submitter`. Three scalar counters track workflows, tasks, and graphs. DEPEND uses zero persistent `DynRay` and zero persistent `DynArray`; all task and graph iteration is bounded by `MAX_TASKS = 6`.

## Contract interface

### Writes

```text
create_workflow(name: str, policy: str) -> str
submit_task(workflow_id: str, task_key: str, task_text: str) -> str
seal_workflow(workflow_id: str) -> None
map_dependencies(workflow_id: str) -> str
complete_task(workflow_id: str, task_id: str) -> str
```

### Views

```text
get_workflow(workflow_id: str) -> dict
get_workflow_status(workflow_id: str) -> str
get_task(task_id: str) -> dict
get_task_id(workflow_id: str, slot: u256) -> str
get_graph(graph_id: str) -> dict
get_dependency(task_id: str) -> dict
get_prerequisite_mask(task_id: str) -> u256
get_ready_mask(workflow_id: str) -> u256
is_task_ready(workflow_id: str, task_id: str) -> bool
get_latest_workflow_for_owner(owner: Address) -> str
get_my_latest_workflow() -> str
get_latest_task_by_submitter(submitter: Address) -> str
get_my_latest_task() -> str
```

The contract has no constructor arguments. The latest-workflow and latest-task maps are discovery pointers; authorization uses explicit workflow and task records.

## Deployment and live example

DEPEND is deployed on GenLayer Studio Next, chain ID `61997`. The local project contains no independently recorded deployment address, so none is listed here.

The live workflow was **Project Atlas Release Workflow**, ID `wrk-6c6737ac56d78256f059cb8da0e5fc69817e1e463f0bc8591a15b4ce82412896`. Its policy was: “Identify only strict prerequisite relationships between tasks. A task depends on another task only when the prerequisite task must be completed before the dependent task can validly begin. Do not treat priority, importance, convenience, or a preference to do something earlier as a dependency. Tasks that can validly proceed independently must remain independent.”

Its four tasks and IDs, in slot order, were:

```text
1 Deploy database schema       tsk-fa7e0f17465d66bc4b31fa36719592ba34feec9e57847c25401f1d2b6a7d07bb
2 Validate migration           tsk-d2e3eab71134373509b2de14864cdf0c073b8acd82cb2c2c4d4cde50217d2cc9
3 Enable production release   tsk-0b1db8e2a1556dabc1c60c380a512df780f0382833dfa13dd24a7bea161662e3
4 Prepare release notes       tsk-cfb0e9f128bfe04bf58dfc0603dbd0f4b5c9070e2f93920d680262e03126a21c
```

The live `map_dependencies` result was `MAPPED`, with canonical masks `[0, 1, 3, 0]`, and graph ID `dpg-2b39beb2b455aeb5d6f3d02861d4d26903aad7de05c33ac7ff1fb75328ec9901`. `get_ready_mask` returned `9`, showing that slots 1 and 4 were ready simultaneously. This live example did not test completion progression, the final `COMPLETED` state, `UNRESOLVED`, six-task mapping, or native concurrency.

## Verification

The approved source is `contracts/Depend.py`, SHA-256 `d57f2a86ed64fcc77d2ec038d92f22a0ad392f318993be70a82008ee95f2ad47`, with 37,704 UTF-8 bytes. Internal verification reported 30 passed tests, 0 failed, 1 skipped, and no Critical, High, Medium, or Low findings. Pyright passed with 0 errors and one harmless wildcard-import warning. Native ABI reflection, storage allocation, import validation, and static GenVM lint passed. Exact `py-genlayer:5jyc...` validation was blocked because the pinned runner archive was unavailable.
