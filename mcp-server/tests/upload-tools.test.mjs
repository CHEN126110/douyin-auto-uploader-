import test from "node:test";
import assert from "node:assert/strict";

import { buildUploadStartRequest } from "../core.js";

test("defaults upload start requests to stop before submit", () => {
  const request = buildUploadStartRequest({
    recordId: 1,
  });

  assert.equal(request.path, "/api/upload/start");
  assert.deepEqual(request.body, {
    record_id: 1,
    stop_before_submit: true,
  });
});

test("builds a stop-before-submit request for a single validated upload", () => {
  const request = buildUploadStartRequest({
    recordId: 1,
    stopBeforeSubmit: true,
  });

  assert.equal(request.path, "/api/upload/start");
  assert.deepEqual(request.body, {
    record_id: 1,
    stop_before_submit: true,
  });
});

test("requires explicit final publish confirmation before disabling stop-before-submit", () => {
  assert.throws(
    () => buildUploadStartRequest({ recordId: 1, stopBeforeSubmit: false }),
    /confirmFinalPublish=true/
  );

  const request = buildUploadStartRequest({
    recordId: 1,
    stopBeforeSubmit: false,
    confirmFinalPublish: true,
  });

  assert.deepEqual(request.body, {
    record_id: 1,
    stop_before_submit: false,
    confirm_final_publish: true,
  });
});

test("builds all-products upload requests through the explicit start-all endpoint", () => {
  const request = buildUploadStartRequest({
    allProducts: true,
    stopBeforeSubmit: true,
  });

  assert.equal(request.path, "/api/upload/start-all");
  assert.deepEqual(request.body, {
    stop_before_submit: true,
  });
});

test("rejects ambiguous upload start requests", () => {
  assert.throws(
    () => buildUploadStartRequest({ recordId: 1, allProducts: true }),
    /either recordId or allProducts=true/
  );
  assert.throws(
    () => buildUploadStartRequest({}),
    /Provide recordId/
  );
});
