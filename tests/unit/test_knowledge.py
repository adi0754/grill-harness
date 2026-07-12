import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "grill-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common
import knowledge
import state
import workflow_ops


class KnowledgeLifecycleTests(unittest.TestCase):
    def record(self, identifier="KNW-001", **changes):
        record = {
            "id": identifier,
            "conclusion": "退款命令必须携带稳定幂等键",
            "type": "project_practice",
            "applicability": ["退款命令处理"],
            "non_applicability": ["只读查询"],
            "evidence": ["EVD-001"],
            "trust_status": "tentative",
            "source_workflow": "WF-001",
            "formed_at": "2026-07-12T12:00:00+08:00",
            "invalidation_condition": "退款协议不再接受幂等键",
            "replaced_by": None,
        }
        record.update(changes)
        return record

    def workflow(self, root, *, accepted=True):
        self.project_path = Path(root) / "product"
        self.project_path.mkdir(exist_ok=True)
        self.current_baseline = state.current_project_baseline(self.project_path)
        workflow = Path(root) / "项目" / "示例-a1b2c3d4" / "工作流" / "2026-07-12-知识-WF001"
        for name in ("核心文档", "过程产物", "最终产物", "系统"):
            (workflow / name).mkdir(parents=True, exist_ok=True)
        state_payload = {
            "schema_version": 1,
            "workflow_version": 1,
            "project_id": "project-a",
            "workflow_id": "WF-001",
            "git_baseline": self.current_baseline,
            "phases": [
                {"id": "independent_assurance", "status": "completed" if accepted else "in_progress"},
                {"id": "knowledge_archive", "status": "pending"},
            ],
            "artifacts": [],
            "tasks": [],
            "evidence": (
                [{
                    "id": "EVD-001",
                    "kind": "final_acceptance",
                    "status": "completed",
                    "result": "accepted",
                    "current": True,
                    "baseline": self.current_baseline,
                }]
                if accepted
                else []
            ),
            "ledger": [],
            "gates": {
                "final_spec_approval": {
                    "status": "approved",
                    "approval_id": "DEC-800",
                    "artifact_versions": {"final-spec": 1},
                }
            },
        }
        common.atomic_write_yaml(workflow / "系统" / "state.yaml", state_payload)
        common.atomic_write_yaml(
            workflow / "系统" / "artifacts.yaml",
            {"schema_version": 1, "workflow_version": 1, "artifacts": []},
        )
        common.atomic_write_yaml(
            workflow / "系统" / "tasks.yaml",
            {"schema_version": 1, "workflow_version": 1, "tasks": []},
        )
        common.atomic_write_yaml(
            workflow / "系统" / "evidence.yaml",
            {
                "schema_version": 1,
                "workflow_version": 1,
                "evidence": state_payload["evidence"],
            },
        )
        return workflow

    def approve_preview(self, workflow, preview, approval_id, gate):
        state_path = workflow / "系统" / "state.yaml"
        payload = common.read_yaml(state_path)
        payload["ledger"].append({
            "id": approval_id,
            "type": approval_id.split("-", 1)[0],
            "version": 1,
            "status": "approved",
            "approved_by": "user",
            "gate": gate,
            "preview_id": preview["preview_id"],
        })
        common.atomic_write_yaml(state_path, payload)

    def test_knowledge_record_requires_stable_identity_and_all_boundary_fields(self):
        report = knowledge.validate_knowledge_record(self.record())
        self.assertTrue(report["valid"], report)

        invalid = self.record(id="REQ-001", evidence=[], replaced_by="not-an-id")
        report = knowledge.validate_knowledge_record(invalid)
        self.assertFalse(report["valid"])
        self.assertTrue({"id", "evidence", "replaced_by"}.issubset(
            {item["field"] for item in report["conflicts"]}
        ))

    def test_query_is_read_only_at_any_phase_and_does_not_create_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "missing-storage"

            result = knowledge.query_knowledge("project-a", "幂等", storage_root=root)

            self.assertEqual(result["records"], [])
            self.assertTrue(result["read_only"])
            self.assertFalse(root.exists())

    def test_query_preserves_file_hashes_and_phase_and_isolates_projects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_a = root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml"
            project_b = root / "知识库" / "项目知识" / "project-b" / "knowledge.yaml"
            general = root / "知识库" / "通用知识" / "knowledge.yaml"
            common.atomic_write_yaml(project_a, {"schema_version": 1, "records": [self.record()]})
            common.atomic_write_yaml(
                project_b,
                {"schema_version": 1, "records": [self.record("KNW-002", conclusion="另一个项目秘密")]},
            )
            common.atomic_write_yaml(
                general,
                {"schema_version": 1, "records": [self.record("KNW-003", conclusion="通用幂等经验")]},
            )
            workflow = self.workflow(root)
            state_path = workflow / "系统" / "state.yaml"
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            phase_before = common.read_yaml(state_path)["phases"]

            result = knowledge.query_knowledge("project-a", "幂等", storage_root=root)

            self.assertEqual({item["id"] for item in result["records"]}, {"KNW-001", "KNW-003"})
            self.assertNotIn("另一个项目秘密", json.dumps(result, ensure_ascii=False))
            after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(after, before)
            self.assertEqual(common.read_yaml(state_path)["phases"], phase_before)

    def test_invalidated_and_replaced_knowledge_cannot_guide_planning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml"
            records = [
                self.record(trust_status="invalidated"),
                self.record("KNW-002", trust_status="replaced", replaced_by="KNW-003"),
                self.record("KNW-003", trust_status="verified", conclusion="当前幂等规则"),
            ]
            common.atomic_write_yaml(path, {"schema_version": 1, "records": records})

            result = knowledge.query_knowledge("project-a", storage_root=root)

            self.assertEqual([item["id"] for item in result["guidance"]], ["KNW-003"])
            self.assertEqual({item["id"] for item in result["historical"]}, {"KNW-001", "KNW-002"})
            self.assertTrue(all(not item["can_guide_planning"] for item in result["historical"]))

    def test_learning_draft_is_written_only_under_current_workflow_and_remains_tentative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root, accepted=False)
            record = self.record(trust_status="verified")
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                result = knowledge.write_learning_draft(workflow, record)

            path = Path(result["path"])
            self.assertEqual(path.parent, (workflow / "过程产物" / "学习草稿").resolve())
            self.assertEqual(result["record"]["trust_status"], "tentative")
            self.assertEqual(common.read_yaml(path)["trust_status"], "tentative")

    def test_unaccepted_workflow_cannot_formally_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root, accepted=False)
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [self.record()]
                )
                self.approve_preview(workflow, preview, "DEC-900", "knowledge_archive")
                with self.assertRaisesRegex(ValueError, "independent assurance|acceptance"):
                    knowledge.promote_project_knowledge(
                        workflow,
                        "project-a",
                        preview=preview["path"],
                        approval_id="DEC-900",
                        project_path=self.project_path,
                    )
            self.assertFalse(
                (root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml").exists()
            )

    def test_project_promotion_preserves_conflicts_with_replaced_by_and_completes_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            existing = self.record(trust_status="verified")
            path = root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml"
            common.atomic_write_yaml(path, {"schema_version": 1, "records": [existing]})
            replacement = self.record(
                "KNW-002",
                conclusion="退款命令必须使用版本化幂等键",
                replaces=["KNW-001"],
            )
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [replacement]
                )
                before_apply = path.read_bytes()
                self.approve_preview(workflow, preview, "DEC-900", "knowledge_archive")
                result = knowledge.promote_project_knowledge(
                    workflow,
                    "project-a",
                    preview=preview["path"],
                    approval_id="DEC-900",
                    project_path=self.project_path,
                )

            self.assertNotEqual(path.read_bytes(), before_apply)
            stored = common.read_yaml(path)["records"]
            old = next(item for item in stored if item["id"] == "KNW-001")
            new = next(item for item in stored if item["id"] == "KNW-002")
            self.assertEqual(old["trust_status"], "replaced")
            self.assertEqual(old["replaced_by"], "KNW-002")
            self.assertEqual(new["trust_status"], "verified")
            self.assertEqual(result["preview"]["replacements"], [
                {"old_id": "KNW-001", "replaced_by": "KNW-002"}
            ])
            phase = next(
                item for item in common.read_yaml(workflow / "系统" / "state.yaml")["phases"]
                if item["id"] == "knowledge_archive"
            )
            self.assertEqual(phase["status"], "completed")

    def test_preview_records_and_base_hash_come_from_one_store_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            path = root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml"
            common.atomic_write_yaml(
                path,
                {"schema_version": 1, "records": [self.record(trust_status="verified")]},
            )
            concurrent = self.record(
                "KNW-003",
                conclusion="并发写入的另一条事实",
                type="repository_fact",
                applicability=["存储层"],
                trust_status="verified",
            )
            original_load = knowledge._load_records

            def load_then_concurrently_change(source):
                records = original_load(source)
                if Path(source).resolve() == path.resolve():
                    common.atomic_write_yaml(
                        path,
                        {"schema_version": 1, "records": records + [concurrent]},
                    )
                return records

            candidate = self.record(
                "KNW-002",
                conclusion="另一类候选事实",
                type="testing_practice",
                applicability=["测试"],
            )
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                with mock.patch.object(
                    knowledge, "_load_records", side_effect=load_then_concurrently_change
                ):
                    preview = knowledge.promote_project_knowledge(
                        workflow, "project-a", [candidate]
                    )

            payload = common.read_yaml(preview["path"])
            current_hash = knowledge._store_hash(path)
            current_ids = {item["id"] for item in common.read_yaml(path)["records"]}
            preview_ids = {item["id"] for item in payload["preview"]["records"]}
            self.assertTrue(
                payload["base_store_hash"] != current_hash
                or current_ids.issubset(preview_ids)
            )

    def test_preview_requires_an_explicit_replaced_by_link_for_conflicting_current_fact(self):
        existing = self.record(trust_status="verified")
        candidate = self.record(
            "KNW-002",
            conclusion="退款命令不得携带幂等键",
        )

        preview = knowledge.preview_promotion([existing], [candidate])

        self.assertFalse(preview["ready"])
        self.assertEqual(preview["records"], [existing])
        self.assertIn("replaced_by", preview["conflicts"][0]["conflict"])

    def test_general_promotion_requires_a_separate_second_user_approval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                project_preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [self.record()]
                )
                self.approve_preview(
                    workflow, project_preview, "DEC-900", "knowledge_archive"
                )
                knowledge.promote_project_knowledge(
                    workflow,
                    "project-a",
                    preview=project_preview["path"],
                    approval_id="DEC-900",
                    project_path=self.project_path,
                )
                general_preview = knowledge.promote_general_knowledge(
                    workflow, "project-a", [self.record()]
                )
                self.approve_preview(
                    workflow, general_preview, "DEC-901", "general_knowledge"
                )
                with self.assertRaisesRegex(ValueError, "separate.*approval|second.*approval"):
                    knowledge.promote_general_knowledge(
                        workflow,
                        "project-a",
                        preview=general_preview["path"],
                        approval_id="DEC-900",
                    )
                result = knowledge.promote_general_knowledge(
                    workflow,
                    "project-a",
                    preview=general_preview["path"],
                    approval_id="DEC-900",
                    general_approval_id="DEC-901",
                )

            self.assertEqual(result["scope"], "general")
            self.assertTrue((root / "知识库" / "通用知识" / "knowledge.yaml").is_file())

    def test_general_preview_rejects_a_fact_not_already_verified_for_the_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                with self.assertRaisesRegex(ValueError, "existing verified project"):
                    knowledge.promote_general_knowledge(
                        workflow, "project-a", [self.record()]
                    )

    def test_general_apply_rechecks_that_project_source_is_still_verified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                project_preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [self.record()]
                )
                self.approve_preview(
                    workflow, project_preview, "DEC-900", "knowledge_archive"
                )
                knowledge.promote_project_knowledge(
                    workflow,
                    "project-a",
                    preview=project_preview["path"],
                    approval_id="DEC-900",
                    project_path=self.project_path,
                )
                general_preview = knowledge.promote_general_knowledge(
                    workflow, "project-a", [self.record()]
                )
                self.approve_preview(
                    workflow, general_preview, "DEC-901", "general_knowledge"
                )
                project_path = root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml"
                project_payload = common.read_yaml(project_path)
                project_payload["records"][0]["trust_status"] = "invalidated"
                common.atomic_write_yaml(project_path, project_payload)

                with self.assertRaisesRegex(ValueError, "project knowledge source changed"):
                    knowledge.promote_general_knowledge(
                        workflow,
                        "project-a",
                        preview=general_preview["path"],
                        approval_id="DEC-900",
                        general_approval_id="DEC-901",
                    )

    def test_archive_phase_update_does_not_leave_state_and_manifest_diverged_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            state_path = (workflow / "系统" / "state.yaml").resolve()
            original_replace = common.os.replace

            def fail_state_replace(source, destination):
                if Path(destination).resolve() == state_path:
                    raise OSError("simulated state replace failure")
                return original_replace(source, destination)

            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [self.record()]
                )
                self.approve_preview(workflow, preview, "DEC-900", "knowledge_archive")
                with mock.patch.object(common.os, "replace", side_effect=fail_state_replace):
                    with self.assertRaisesRegex(OSError, "simulated"):
                        knowledge.promote_project_knowledge(
                            workflow,
                            "project-a",
                            preview=preview["path"],
                            approval_id="DEC-900",
                            project_path=self.project_path,
                        )

            state_records = common.read_yaml(state_path)["artifacts"]
            manifest_records = common.read_yaml(workflow / "系统" / "artifacts.yaml")["artifacts"]
            self.assertEqual(state_records, manifest_records)

    def test_transaction_rolls_back_knowledge_and_workflow_after_post_replace_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            knowledge_path = root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml"
            common.atomic_write_yaml(
                knowledge_path,
                {"schema_version": 1, "records": [self.record(trust_status="verified")]},
            )
            candidate = self.record(
                "KNW-002",
                conclusion="另一类候选事实",
                type="testing_practice",
                applicability=["测试"],
            )
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [candidate]
                )
                self.approve_preview(workflow, preview, "DEC-900", "knowledge_archive")
                tracked = [
                    knowledge_path,
                    workflow / "系统" / "state.yaml",
                    workflow / "系统" / "artifacts.yaml",
                    workflow / "系统" / "tasks.yaml",
                    workflow / "系统" / "evidence.yaml",
                ]
                before = {path: path.read_bytes() for path in tracked}
                original_unlink = Path.unlink
                failed = {"value": False}

                def fail_first_journal_unlink(path, *args, **kwargs):
                    if (
                        path.name == workflow_ops.TRANSACTION_FILE
                        and not failed["value"]
                    ):
                        failed["value"] = True
                        raise OSError("simulated post-replace failure")
                    return original_unlink(path, *args, **kwargs)

                with mock.patch.object(Path, "unlink", fail_first_journal_unlink):
                    with self.assertRaisesRegex(OSError, "post-replace"):
                        knowledge.promote_project_knowledge(
                            workflow,
                            "project-a",
                            preview=preview["path"],
                            approval_id="DEC-900",
                            project_path=self.project_path,
                        )

            after = {path: path.read_bytes() for path in tracked}
            self.assertEqual(after, before)
            self.assertFalse((workflow / "系统" / workflow_ops.TRANSACTION_FILE).exists())

    def test_route_failure_exception_is_project_only_and_does_not_complete_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root, accepted=False)
            route_failure = self.record(
                type="route_failure",
                conclusion="事件溯源路线在当前存储约束下失败",
                failure_class="route_failure",
            )
            state_path = workflow / "系统" / "state.yaml"
            payload = common.read_yaml(state_path)
            payload["evidence"] = [{
                "id": "EVD-001",
                "status": "valid",
                "currentness": "current",
                "failure_class": "route_failure",
                "workflow_id": "WF-001",
            }]
            common.atomic_write_yaml(state_path, payload)
            common.atomic_write_yaml(
                workflow / "系统" / "evidence.yaml",
                {"schema_version": 1, "workflow_version": 1, "evidence": payload["evidence"]},
            )
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [route_failure], route_failure=True
                )
                self.approve_preview(workflow, preview, "DEC-910", "route_failure")
                result = knowledge.promote_project_knowledge(
                    workflow,
                    "project-a",
                    preview=preview["path"],
                    route_failure=True,
                    failure_approval_id="DEC-910",
                )
                with self.assertRaisesRegex(ValueError, "route failure.*general"):
                    knowledge.promote_general_knowledge(
                        workflow, "project-a", [route_failure]
                    )

            self.assertTrue(result["route_failure_exception"])
            phase = next(
                item for item in common.read_yaml(workflow / "系统" / "state.yaml")["phases"]
                if item["id"] == "knowledge_archive"
            )
            self.assertEqual(phase["status"], "pending")
            self.assertFalse((root / "知识库" / "通用知识" / "knowledge.yaml").exists())

    def test_route_failure_apply_rechecks_current_owned_evidence_after_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root, accepted=False)
            state_path = workflow / "系统" / "state.yaml"
            payload = common.read_yaml(state_path)
            payload["evidence"] = [{
                "id": "EVD-001",
                "status": "valid",
                "currentness": "current",
                "failure_class": "route_failure",
                "workflow_id": "WF-001",
            }]
            common.atomic_write_yaml(state_path, payload)
            common.atomic_write_yaml(
                workflow / "系统" / "evidence.yaml",
                {"schema_version": 1, "workflow_version": 1, "evidence": payload["evidence"]},
            )
            route_failure = self.record(
                type="route_failure",
                failure_class="route_failure",
            )
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [route_failure], route_failure=True
                )
                self.approve_preview(workflow, preview, "DEC-910", "route_failure")
                stale = common.read_yaml(state_path)
                stale["evidence"][0]["currentness"] = "stale"
                common.atomic_write_yaml(state_path, stale)
                common.atomic_write_yaml(
                    workflow / "系统" / "evidence.yaml",
                    {"schema_version": 1, "workflow_version": 1, "evidence": stale["evidence"]},
                )

                with self.assertRaisesRegex(ValueError, "current, owned"):
                    knowledge.promote_project_knowledge(
                        workflow,
                        "project-a",
                        preview=preview["path"],
                        route_failure=True,
                        failure_approval_id="DEC-910",
                    )

            self.assertFalse(
                (root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml").exists()
            )

    def test_empty_promotion_is_rejected_before_preview_or_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                with self.assertRaisesRegex(ValueError, "at least one"):
                    knowledge.promote_project_knowledge(workflow, "project-a", [])

    def test_apply_rejects_preview_paths_that_are_not_canonical_for_scope_and_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root)
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [self.record()]
                )
                payload = common.read_yaml(preview["path"])
                payload["knowledge_path"] = str(root / "知识库" / "attacker" / "knowledge.yaml")
                core = {key: value for key, value in payload.items() if key != "preview_id"}
                payload["preview_id"] = knowledge._preview_id(core)
                common.atomic_write_yaml(Path(preview["path"]), payload)
                tampered = dict(preview, preview_id=payload["preview_id"])
                self.approve_preview(workflow, tampered, "DEC-900", "knowledge_archive")

                with self.assertRaisesRegex(ValueError, "canonical knowledge path"):
                    knowledge.promote_project_knowledge(
                        workflow,
                        "project-a",
                        preview=preview["path"],
                        approval_id="DEC-900",
                    )

            self.assertFalse((root / "知识库" / "attacker" / "knowledge.yaml").exists())

    def test_route_failure_apply_validates_only_candidate_evidence_not_historical_facts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = self.workflow(root, accepted=False)
            state_path = workflow / "系统" / "state.yaml"
            payload = common.read_yaml(state_path)
            payload["evidence"] = [{
                "id": "EVD-NEW",
                "status": "valid",
                "currentness": "current",
                "failure_class": "route_failure",
                "workflow_id": "WF-001",
            }]
            common.atomic_write_yaml(state_path, payload)
            common.atomic_write_yaml(
                workflow / "系统" / "evidence.yaml",
                {"schema_version": 1, "workflow_version": 1, "evidence": payload["evidence"]},
            )
            old = self.record(
                "KNW-001",
                type="route_failure",
                failure_class="route_failure",
                evidence=["EVD-OLD"],
                trust_status="verified",
            )
            path = root / "知识库" / "项目知识" / "project-a" / "knowledge.yaml"
            common.atomic_write_yaml(path, {"schema_version": 1, "records": [old]})
            candidate = self.record(
                "KNW-002",
                conclusion="新路线在当前约束下失败",
                type="route_failure",
                failure_class="route_failure",
                evidence=["EVD-NEW"],
                replaces=["KNW-001"],
            )
            with mock.patch.dict(os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}):
                preview = knowledge.promote_project_knowledge(
                    workflow, "project-a", [candidate], route_failure=True
                )
                self.approve_preview(workflow, preview, "DEC-910", "route_failure")
                result = knowledge.promote_project_knowledge(
                    workflow,
                    "project-a",
                    preview=preview["path"],
                    route_failure=True,
                    failure_approval_id="DEC-910",
                )

            self.assertTrue(result["applied"])
            self.assertEqual(
                {item["id"] for item in common.read_yaml(path)["records"]},
                {"KNW-001", "KNW-002"},
            )

    def test_formal_apply_fails_closed_without_typed_current_project_baseline(self):
        for invalid_baseline in (None, True):
            with self.subTest(invalid_baseline=invalid_baseline):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workflow = self.workflow(root)
                    with mock.patch.dict(
                        os.environ, {common.TEST_STORAGE_ROOT_ENV: str(root)}
                    ):
                        preview = knowledge.promote_project_knowledge(
                            workflow, "project-a", [self.record()]
                        )
                        self.approve_preview(
                            workflow, preview, "DEC-900", "knowledge_archive"
                        )
                        state_path = workflow / "系统" / "state.yaml"
                        payload = common.read_yaml(state_path)
                        payload["git_baseline"] = invalid_baseline
                        payload["evidence"][0]["baseline"] = invalid_baseline
                        common.atomic_write_yaml(state_path, payload)
                        common.atomic_write_yaml(
                            workflow / "系统" / "evidence.yaml",
                            {
                                "schema_version": 1,
                                "workflow_version": 1,
                                "evidence": payload["evidence"],
                            },
                        )

                        with self.assertRaisesRegex(ValueError, "current prerequisites"):
                            knowledge.promote_project_knowledge(
                                workflow,
                                "project-a",
                                preview=preview["path"],
                                approval_id="DEC-900",
                                project_path=self.project_path,
                            )


if __name__ == "__main__":
    unittest.main()
