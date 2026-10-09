# -*- coding: utf-8 -*-
"""链尾按当前页面实际必填标记核对；未提供的必填属性也不能漏检。"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import unittest
from unittest import mock

SUBPROJECT = pathlib.Path(__file__).resolve().parents[1]
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages
from taobao_publish.models import PublishItem


def facts(*required):
    return {"known": True, "rowCount": max(1, len(required)),
            "scope": "visible_property_label_required", "completePage": False,
            "required": list(required)}


def field(label="适用季节", supported=True, hits=1):
    return {"label": label, "supportedReader": supported, "hitCount": hits}


class RequiredPropertyReadbackTest(unittest.TestCase):
    def run_readback(self, snapshot, value="", error=None):
        ctx = stages.PipelineContext(item=PublishItem(record_id=1, record_name="ID-1", title="标题"), dry_run=False)
        with mock.patch.object(stages, "_open_publish_page", return_value=mock.Mock()), \
                mock.patch.object(page, "read_text_field", return_value="标题"), \
                mock.patch.object(page, "read_submit_state", return_value={"submit": {
                    "present": True, "visible": True, "disabled": False}}), \
                mock.patch.object(page, "read_selected_options", return_value=[]), \
                mock.patch.object(page, "read_required_form", return_value={'known': True, 'scope': 'visible_publish_rows_required', 'completePage': False, 'rowCount': 1, 'required': [], 'unownedRequiredCount': 0}), \
                mock.patch.object(page, "read_required_properties", return_value=snapshot), \
                mock.patch.object(page, "read_prop_value", return_value=value, side_effect=error) as reader:
            outcome = stages.stage_readback(ctx)
        return outcome, ctx, reader

    def test_unprovided_required_property_with_an_empty_actual_value_fails(self):
        outcome, ctx, reader = self.run_readback(facts(field()), "")
        self.assertFalse(outcome.ok)
        self.assertTrue(any(blocker.code == "REQUIRED_FIELD_MISSING" and blocker.field == "适用季节"
                            for blocker in outcome.blockers))
        reader.assert_called_once()
        self.assertTrue(ctx.scratch["readback"]["required_blockers"])

    def test_a_required_property_with_an_actual_value_passes_with_partial_coverage(self):
        outcome, ctx, _reader = self.run_readback(facts(field()), "秋季")
        self.assertTrue(outcome.ok, outcome.summary)
        coverage = outcome.data["required_field_coverage"]
        self.assertEqual(coverage["checked"], [{"label": "适用季节", "value": "秋季"}])
        self.assertFalse(coverage["completePage"])
        self.assertIn("尚不代表整页", outcome.summary)
        self.assertFalse(ctx.item.props)

    def test_unknown_required_facts_cannot_be_reported_as_zero_required_fields(self):
        outcome, _ctx, reader = self.run_readback({"known": False, "required": []})
        self.assertFalse(outcome.ok)
        self.assertTrue(any(blocker.code == "EVIDENCE_INSUFFICIENT" for blocker in outcome.blockers))
        reader.assert_not_called()

    def test_an_unknown_required_control_has_a_specific_blocker(self):
        outcome, _ctx, reader = self.run_readback(facts(field(supported=False)))
        self.assertFalse(outcome.ok)
        self.assertTrue(any(blocker.code == "UNSUPPORTED_REQUIRED_FIELD" for blocker in outcome.blockers))
        reader.assert_not_called()

    def test_duplicate_required_labels_do_not_select_the_first_row(self):
        outcome, _ctx, reader = self.run_readback(facts(field(hits=2)))
        self.assertFalse(outcome.ok)
        self.assertTrue(any(blocker.code == "READBACK_UNREADABLE" for blocker in outcome.blockers))
        reader.assert_not_called()

    def test_required_reader_failure_is_not_an_empty_default(self):
        outcome, _ctx, _reader = self.run_readback(facts(field()), error=page.PageError("控件不可读取"))
        self.assertFalse(outcome.ok)
        self.assertTrue(any("控件不可读取" in blocker.detail for blocker in outcome.blockers))

    def test_no_required_markers_in_known_property_rows_still_has_only_partial_coverage(self):
        outcome, _ctx, _reader = self.run_readback(facts())
        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(outcome.data["required_field_coverage"]["checkedCount"], 0)
        self.assertFalse(outcome.data["required_field_coverage"]["completePage"])


class RequiredFactsValidationTest(unittest.TestCase):
    def test_an_empty_payload_is_unknown(self):
        client = mock.Mock()
        client.evaluate.return_value = {}
        self.assertFalse(page.read_required_properties(client)["known"])

    def test_a_payload_without_property_rows_is_unknown(self):
        client = mock.Mock()
        client.evaluate.return_value = {**facts(), "rowCount": 0}
        self.assertFalse(page.read_required_properties(client)["known"])

    def test_non_dict_required_entries_are_unknown(self):
        client = mock.Mock()
        client.evaluate.return_value = {**facts(), "required": ["适用季节"]}
        self.assertFalse(page.read_required_properties(client)["known"])


@unittest.skipUnless(shutil.which("node"), "需要 Node 执行隔离 DOM 表达式")
class RequiredPropertyDomTest(unittest.TestCase):
    def evaluate(self, rows):
        fixture = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const rows = input.rows.map(info => {
  const row = {
    getBoundingClientRect: () => ({width: info.hidden ? 0 : 100, height: info.hidden ? 0 : 20}),
    querySelector: selector => selector === 'label' ? label
      : selector.split(',').map(s => s.trim()).includes('input') && info.reader ? {type: 'text'} : null,
  };
  const label = {textContent: info.label, closest: () => row,
                 matches: () => info.required === true};
  return row;
});
global.document = {querySelectorAll: () => rows};
process.stdout.write(JSON.stringify(eval(input.expression)));
"""
        result = subprocess.run([shutil.which("node"), "-e", fixture],
                                input=json.dumps({"rows": rows, "expression": page.build_read_required_properties_expression()}, ensure_ascii=False),
                                text=True, encoding="utf-8", capture_output=True, timeout=10, check=True)
        return json.loads(result.stdout)

    def test_only_current_visible_required_labels_are_reported(self):
        output = self.evaluate([
            {"label": "适用季节", "required": True, "reader": True},
            {"label": "可选面料", "required": False, "reader": True},
            {"label": "隐藏其它类目属性", "required": True, "reader": True, "hidden": True},
        ])
        self.assertTrue(output["known"])
        self.assertEqual(output["required"], [field()])
        self.assertFalse(output["completePage"])

    def test_no_property_rows_means_unknown_not_zero_required(self):
        self.assertFalse(self.evaluate([])["known"])


if __name__ == "__main__":
    unittest.main()
