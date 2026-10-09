const WHOLE_FORM_SCOPE = "whole_publish_form_required_fields";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validLabel(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value === value.trim();
}

/** 必填清单、读取能力和实际回读值都齐全，才能接受整页覆盖声明。 */
export function isConfirmedWholeFormCoverage(value: unknown): boolean {
  if (!isRecord(value) || value.known !== true || value.completePage !== true ||
      value.scope !== WHOLE_FORM_SCOPE) return false;

  const { rowCount, required, checked, checkedCount } = value;
  if (typeof rowCount !== "number" || !Number.isSafeInteger(rowCount) || rowCount < 1 ||
      !Array.isArray(required) || required.length < 1 || required.length > rowCount ||
      !Array.isArray(checked) || required.length !== checked.length ||
      checkedCount !== checked.length) return false;

  const expectedLabels = new Set<string>();
  for (const entry of required) {
    if (!isRecord(entry) || !validLabel(entry.label) || entry.hitCount !== 1 ||
        entry.supportedReader !== true || expectedLabels.has(entry.label)) return false;
    expectedLabels.add(entry.label);
  }
  const checkedLabels = new Set<string>();
  for (const entry of checked) {
    if (!isRecord(entry) || !validLabel(entry.label) ||
        typeof entry.value !== "string" || !entry.value.trim() ||
        !expectedLabels.has(entry.label) || checkedLabels.has(entry.label)) return false;
    checkedLabels.add(entry.label);
  }
  return checkedLabels.size === expectedLabels.size;
}

/** 局部必填事实只用于否决，不能替代整页覆盖证明。 */
function visibleRequirementsHaveNoFailures(value: unknown, coverage: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (!isRecord(value) || value.known !== true || value.completePage !== false ||
      value.scope !== "visible_publish_rows_required" || value.unownedRequiredCount !== 0 ||
      typeof value.rowCount !== "number" || !Number.isSafeInteger(value.rowCount) || value.rowCount < 1 ||
      !Array.isArray(value.required) || value.required.length > value.rowCount) return false;
  if (!isRecord(coverage) || !Array.isArray(coverage.required)) return false;
  const coveredLabels = new Set(coverage.required.filter(isRecord).map(field => field.label));
  const labels = new Set<string>();
  for (const field of value.required) {
    if (!isRecord(field) || !validLabel(field.label) || labels.has(field.label) || field.hitCount !== 1 ||
        field.supportedReader !== true || field.filled !== true || field.valid !== true) return false;
    if (!coveredLabels.has(field.label)) return false;
    labels.add(field.label);
  }
  return true;
}

/** 淘宝本次入口只验收真实填写后停在提交前，任务终态本身不是填写证据。 */
export function isVerifiedTaobaoFillResult(task: unknown): boolean {
  if (!isRecord(task) || task.platform !== "taobao" || task.status !== "succeeded" || task.dry_run !== false ||
      task.stop_before_submit !== true || task.publish_confirmed !== false ||
      !isRecord(task.result)) return false;
  const result = task.result;
  if (result.success !== true || result.stopped_before_submit !== true ||
      !isRecord(result.data) || !isRecord(result.data.form_verification)) return false;
  const verification = result.data.form_verification;
  return verification.status === "complete" && verification.complete === true &&
    isConfirmedWholeFormCoverage(verification.required_field_coverage) &&
    visibleRequirementsHaveNoFailures(verification.visible_form_requirements, verification.required_field_coverage);
}
