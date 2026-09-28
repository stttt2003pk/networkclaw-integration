from __future__ import annotations

import json
import ast
import os
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = Path(os.environ.get("NETWORKCLAW_HARNESS_ROOT", ROOT.parent / "networkclaw-harness"))
CATALOG_PATH = ROOT / "schemas/events/event-catalog-v1.json"
ENVELOPE_PATH = ROOT / "schemas/events/event-envelope-v1.schema.json"
INVENTORY_PATH = ROOT / "docs/evidence/hermes-event-inventory.json"
STATE_MACHINE_PATH = ROOT / "docs/contracts/process-tree-state-machine.json"
FIXTURE_PATH = ROOT / "tests/fixtures/events/process-tree-fixture.json"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


class EventContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_json(CATALOG_PATH)
        cls.schema = load_json(ENVELOPE_PATH)
        cls.inventory = load_json(INVENTORY_PATH)
        cls.state_machine = load_json(STATE_MACHINE_PATH)
        cls.fixture = load_json(FIXTURE_PATH)

    def test_baseline_catalog_is_frozen_and_extensions_do_not_alias_it(self) -> None:
        baseline = [event["name"] for event in self.catalog["baseline_events"]]
        extensions = [event["name"] for event in self.catalog["process_extensions"]]
        self.assertEqual(self.catalog["baseline_event_count"], 36)
        self.assertEqual(len(baseline), 36)
        self.assertEqual(len(baseline), len(set(baseline)))
        self.assertEqual(len(extensions), len(set(extensions)))
        self.assertTrue(set(baseline).isdisjoint(extensions))
        inventory_names = {item["name"] for item in self.inventory["events"]}
        self.assertTrue(set(extensions) <= inventory_names)
        self.assertIn("delegation.requested", inventory_names)

    def test_catalog_matches_harness_catalog_and_inventory_sources(self) -> None:
        if not HARNESS_ROOT.is_dir():
            self.skipTest(f"Harness checkout not available: {HARNESS_ROOT}")

        catalog_source = HARNESS_ROOT / "src/networkclaw_harness/protocol/catalog.py"
        module = ast.parse(catalog_source.read_text(encoding="utf-8"), filename=str(catalog_source))
        assignments = {
            node.targets[0].id: node.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"EVENTS", "PROCESS_EXTENSIONS"}
        }

        def frozen_set(name: str) -> set[str]:
            value = assignments[name]
            self.assertIsInstance(value, ast.Call)
            self.assertEqual(ast.unparse(value.func), "frozenset")
            return set(ast.literal_eval(value.args[0]))

        self.assertEqual(frozen_set("EVENTS"), {item["name"] for item in self.catalog["baseline_events"]})
        self.assertEqual(
            frozen_set("PROCESS_EXTENSIONS"),
            {item["name"] for item in self.catalog["process_extensions"]},
        )

        for item in self.inventory["events"]:
            source = HARNESS_ROOT / item["source_path"]
            self.assertTrue(source.is_file(), item["source_path"])
            line_count = len(source.read_text(encoding="utf-8").splitlines())
            for span in item["source_lines"].split(","):
                bounds = [int(part) for part in span.split("-")]
                if len(bounds) == 1:
                    bounds.append(bounds[0])
                self.assertEqual(len(bounds), 2, span)
                self.assertGreaterEqual(bounds[0], 1, span)
                self.assertLessEqual(bounds[0], bounds[1], span)
                self.assertLessEqual(bounds[1], line_count, f"{source}:{span}")

    def test_catalog_exclusions_do_not_match_declared_events(self) -> None:
        declared = [event["name"] for event in self.catalog["baseline_events"]]
        declared += [event["name"] for event in self.catalog["process_extensions"]]
        for excluded in self.catalog["excluded_events"]:
            pattern = excluded["pattern"]
            if pattern.endswith(".*"):
                prefix = pattern[:-1]
                self.assertFalse(any(name.startswith(prefix) for name in declared), pattern)
            else:
                self.assertNotIn(pattern, declared)

    def test_extension_surfaces_match_inventory_permissions(self) -> None:
        inventory = {item["name"]: item for item in self.inventory["events"]}
        for item in self.catalog["process_extensions"]:
            source = inventory[item["name"]]
            self.assertEqual(item["surface"], source["default_surface"], item["name"])
            self.assertEqual(item["source_path"], source["source_path"], item["name"])
            self.assertTrue(source["permission"], item["name"])

    def test_process_identity_is_required_but_process_control_needs_no_session(self) -> None:
        validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        for name in ("subagent_progress", "finalizer.fallback", "tool.progress", "turn.completed"):
            event = dict(self.fixture["events"][0], type=name)
            self.assertTrue(validator.is_valid(event))
            for key in ("session_id", "run_id", "turn_id", "event_id"):
                incomplete = {k: v for k, v in event.items() if k != key}
                self.assertFalse(validator.is_valid(incomplete), f"{name} without {key}")
        control = {k: v for k, v in self.fixture["events"][0].items()
                   if k not in {"session_id", "run_id", "turn_id", "event_id"}}
        self.assertTrue(validator.is_valid(dict(control, type="end", end=True)))

    def test_fixture_is_valid_envelope_and_uses_only_catalog_events(self) -> None:
        allowed = {
            event["name"] for event in self.catalog["baseline_events"]
        } | {
            event["name"] for event in self.catalog["process_extensions"]
        }
        validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        events = self.fixture["events"]
        self.assertGreaterEqual(len(events), 20)
        self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(len({event["event_id"] for event in events}), len(events))
        for event in events:
            self.assertIn(event["type"], allowed)
            errors = sorted(validator.iter_errors(event), key=lambda error: error.path)
            self.assertEqual(errors, [], errors)

    def test_lineage_reconstructs_two_children_and_their_work(self) -> None:
        for events in (self.fixture["events"], list(reversed(self.fixture["events"]))):
            with self.subTest(arrival="ordered" if events[0]["sequence"] == 1 else "reversed"):
                self.assert_process_lineage(events)

    def assert_process_lineage(self, events: list[dict]) -> None:
        allocations = {
            event["payload"]["allocation_id"]: event["payload"]["child_session_id"]
            for event in events
            if event["type"] == "delegation.resolved"
        }
        children = {
            event["payload"]["subagent_id"]: event["session_id"]
            for event in events
            if event["type"] == "subagent.start"
        }
        self.assertEqual(set(allocations), {"allocation-1", "allocation-2"})
        self.assertEqual(set(children.values()), {"session-child-a", "session-child-b"})
        for event in events:
            if event["type"].startswith("subagent."):
                payload = event["payload"]
                self.assertIn(payload["allocation_id"], allocations)
                self.assertEqual(allocations[payload["allocation_id"]], event["session_id"])
                self.assertEqual(payload["parent_session_id"], "session-parent")
            if event["type"].startswith("tool."):
                self.assertEqual(event["payload"]["parent_item_id"], "subagent-a")
                self.assertEqual(event["invocation_id"], "invocation-a")
        artifact = next(event for event in events if event["type"] == "artifact.created")
        self.assertEqual(artifact["parent_item_id"], "subagent-a")
        self.assertEqual(artifact["artifact_id"], "artifact-1")
        self.assertEqual(
            [event["type"] for event in sorted(events, key=lambda event: event["sequence"])
             if event["type"].startswith("approval.")],
            ["approval.requested", "approval.resolved"],
        )

    def test_process_tree_state_machine_covers_fixture_and_terminal_latches(self) -> None:
        node_events = {
            event_name
            for node in self.state_machine["nodes"].values()
            for event_name in node["events"]
        }
        self.assertTrue({event["type"] for event in self.fixture["events"]} <= node_events)
        terminal = [event for event in self.fixture["events"] if event["end"]]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["type"], "turn.completed")
        self.assertTrue(self.state_machine["projection_rules"]["terminal_latch"].startswith("first terminal"))

    def test_fixture_has_no_raw_reasoning_or_secret_fields(self) -> None:
        forbidden = {"raw_reasoning", "reasoning_content", "chain_of_thought", "scratchpad", "secret", "token", "authorization"}

        def walk(value: object) -> list[str]:
            found: list[str] = []
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.casefold() in forbidden:
                        found.append(key)
                    found.extend(walk(child))
            elif isinstance(value, list):
                for child in value:
                    found.extend(walk(child))
            return found

        self.assertEqual(walk(self.fixture), [])


if __name__ == "__main__":
    unittest.main()
