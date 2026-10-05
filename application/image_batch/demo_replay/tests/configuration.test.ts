import test from "node:test";
import assert from "node:assert/strict";
import { capturedWorkers } from "../tools/normalize.ts";
test("uses captured application capacity independently of configured VM cores", () => {
  const invocation = {
    workers: ["a", "b", "c", "d", "e", "f"],
    worker_cores: 6,
    worker_memory_mib: 8192,
  };
  const recorded = invocation.workers.map((node_name) => ({
    node_name,
    configured_cores: 6,
    configured_memory_mib: 8192,
    modeled_cores: 3,
  }));
  assert.deepEqual(
    capturedWorkers(invocation, recorded).map((w) => w.slots),
    [3, 3, 3, 3, 3, 3],
  );
  assert.throws(
    () => capturedWorkers(invocation, recorded.slice(1)),
    /capacity/i,
  );
});
