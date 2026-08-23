"""
Security Hardening Tests for DataOS (Rule #14, Rule #50, Rule #61, Rule #63).
Validates AST security sandboxing, attack vector interception, execution timeouts,
memory/payload caps, and agent privilege escalation prevention.
"""

import unittest
import tempfile
import os
import time
from infrastructure.storage.sqlite_store import SQLiteStorage
from engines.compute.python_sandbox import PythonSandbox, SecurityViolationError
from core.governance.resource_governor import ResourceGovernor, ResourceQuota, RateLimitExceededError, QuotaExceededError
from runtime.agents.agent import AgentHarness


class TestSecurityHardening(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.sandbox = PythonSandbox(self.storage, default_timeout_seconds=1.0)
        self.governor = ResourceGovernor()

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    # -------------------------------------------------------------------------
    # 1. AST IMPORT INTERCEPTION TESTS
    # -------------------------------------------------------------------------

    def test_blocks_os_and_sys_imports(self):
        for malicious_code in [
            "import os\nos.system('echo hacked')",
            "import sys\nsys.exit(1)",
            "import subprocess\nsubprocess.run(['ls'])",
            "import socket\ns = socket.socket()",
            "import urllib.request\nurllib.request.urlopen('http://evil.com')",
            "import ctypes\nctypes.CDLL(None)"
        ]:
            res = self.sandbox.execute_code(malicious_code)
            self.assertFalse(res["success"])
            self.assertTrue(res["security_violation"])
            self.assertIn("prohibited in sandbox", res["error"])

    def test_blocks_from_import_syntax(self):
        for malicious_code in [
            "from os import system\nsystem('echo hacked')",
            "from subprocess import Popen",
            "from sys import modules"
        ]:
            res = self.sandbox.execute_code(malicious_code)
            self.assertFalse(res["success"])
            self.assertTrue(res["security_violation"])

    # -------------------------------------------------------------------------
    # 2. DANGEROUS BUILTIN & DUNDER ESCALATION TESTS
    # -------------------------------------------------------------------------

    def test_blocks_eval_exec_open_builtins(self):
        for malicious_code in [
            "eval('2 + 2')",
            "exec('a = 1')",
            "f = open('config.env', 'r')",
            "g = globals()",
            "l = locals()"
        ]:
            res = self.sandbox.execute_code(malicious_code)
            self.assertFalse(res["success"])
            self.assertTrue(res["security_violation"])

    def test_blocks_dunder_subclasses_escalation(self):
        # Python sandbox escape exploit via object.__subclasses__()
        exploit_code = """
classes = ().__class__.__bases__[0].__subclasses__()
for c in classes:
    if c.__name__ == 'BuiltinImporter':
        c().load_module('os').system('echo hacked')
"""
        res = self.sandbox.execute_code(exploit_code)
        self.assertFalse(res["success"])
        self.assertTrue(res["security_violation"])
        self.assertIn("dangerous attribute", res["error"])

    def test_blocks_async_and_concurrency_constructs(self):
        async_code = """
async def background_task():
    pass
"""
        res = self.sandbox.execute_code(async_code)
        self.assertFalse(res["success"])
        self.assertTrue(res["security_violation"])

    # -------------------------------------------------------------------------
    # 3. EXECUTION TIMEOUT ENFORCEMENT
    # -------------------------------------------------------------------------

    def test_execution_timeout_kills_infinite_loop(self):
        infinite_loop = """
import time
start = time.time()
while True:
    if time.time() - start > 100:
        break
"""
        res = self.sandbox.execute_code(infinite_loop, timeout_seconds=0.3)
        self.assertFalse(res["success"])
        self.assertTrue(res["timeout_exceeded"])
        self.assertIn("ExecutionTimeoutError", res["error"])

    # -------------------------------------------------------------------------
    # 4. MEMORY / PAYLOAD SIZE LIMITS
    # -------------------------------------------------------------------------

    def test_output_payload_cap_enforcement(self):
        small_cap_sandbox = PythonSandbox(self.storage, max_output_payload_bytes=500)
        large_output_code = """
results['large_data'] = 'A' * 2000
"""
        res = small_cap_sandbox.execute_code(large_output_code)
        self.assertFalse(res["success"])
        self.assertIn("MemoryPayloadExceeded", res["error"])

    # -------------------------------------------------------------------------
    # 5. AGENT CAPABILITY & PRIVILEGE ESCALATION GATING
    # -------------------------------------------------------------------------

    def test_agent_role_capability_enforcement(self):
        from core.permissions.policy import PermissionPolicy, Capability
        policy = PermissionPolicy(
            principal_id="research_agent_01",
            role="researcher",
            allowed_capabilities={Capability.SEARCH.value, Capability.READ_OBJECT.value}
        )
        agent = AgentHarness(agent_id="research_agent_01", policy=policy, storage=self.storage)
        
        # Allowed capability executes without PermissionError
        self.assertTrue(policy.has_capability(Capability.SEARCH.value))
        self.assertTrue(policy.has_capability(Capability.READ_OBJECT.value))

        # Denied capability raises PermissionError
        self.assertFalse(policy.has_capability(Capability.DELETE_OBJECT.value))
        self.assertFalse(policy.has_capability(Capability.COMPUTE_PYTHON.value))
        with self.assertRaises(PermissionError):
            agent.execute_capability(Capability.DELETE_OBJECT, {"object_id": "obj-123"})

    # -------------------------------------------------------------------------
    # 6. RESOURCE GOVERNOR RATE LIMITING & COMPUTE BUDGETS
    # -------------------------------------------------------------------------

    def test_rate_limiter_blocks_excessive_calls(self):
        self.governor.set_quota(ResourceQuota(principal_id="test_agent", max_queries_per_minute=3))
        self.governor.check_and_consume_rate_limit("test_agent")
        self.governor.check_and_consume_rate_limit("test_agent")
        self.governor.check_and_consume_rate_limit("test_agent")

        with self.assertRaises(RateLimitExceededError):
            self.governor.check_and_consume_rate_limit("test_agent")

    def test_compute_quota_blocks_excessive_duration(self):
        self.governor.set_quota(ResourceQuota(principal_id="heavy_agent", max_compute_seconds_per_hour=5.0))
        self.governor.record_compute_usage("heavy_agent", duration_seconds=3.0)

        with self.assertRaises(QuotaExceededError):
            self.governor.record_compute_usage("heavy_agent", duration_seconds=3.0)


if __name__ == "__main__":
    unittest.main()
