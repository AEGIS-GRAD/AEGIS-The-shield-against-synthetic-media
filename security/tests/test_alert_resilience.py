"""
Week 9 Task 5 - Loss-proof alert delivery (resilience tests).

DFS gate: every failure mode of ReliableAlertDestination in isolation.
Includes the headline proof: a real HTTP SIEM mock is killed mid-run, alerts keep
flowing, the SIEM comes back, and every single alert arrives (zero loss).
"""

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from security.incident_response.alert_router import (
    AEGISAlert,
    AlertRouter,
    BaseAlertDestination,
    CameraMetadata,
    EvidenceBundle,
    MemoryAlertDestination,
    ReliableAlertDestination,
    WebhookAlertDestination,
)


def make_alert(n: int = 0, severity: str = "P1_CRITICAL", camera: str = "cam-r") -> AEGISAlert:
    return AEGISAlert(
        severity=severity,
        camera_metadata=CameraMetadata(camera_id=f"{camera}-{n}"),
        threat_classification="CRYPTOGRAPHIC_HASH_MISMATCH",
        anomaly_score=0.9,
        evidence_bundle=EvidenceBundle(
            forensic_hash=f"{n:064x}",
            frame_sequence_range=[n, n + 1],
            technical_detail=f"alert number {n}",
        ),
    )


class FlakyDestination(BaseAlertDestination):
    """Destination whose availability is toggled by the test."""

    def __init__(self):
        self.up = False
        self.raise_on_fail = False
        self.received = []
        self.calls = 0
        self._lock = threading.Lock()

    def deliver(self, alert):
        with self._lock:
            self.calls += 1
            if not self.up:
                if self.raise_on_fail:
                    raise ConnectionError("SIEM down")
                return False
            self.received.append(alert.alert_id)
            return True


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


class TestReliableDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.inner = FlakyDestination()
        self.rel = ReliableAlertDestination(
            self.inner, self.tmp.name, max_attempts=4,
            base_delay_seconds=1.0, max_delay_seconds=8.0, clock=self.clock,
        )

    def tearDown(self):
        self.rel.stop_background()
        self.tmp.cleanup()

    # ── happy path ───────────────────────────────────────────────────────────
    def test_success_passes_through_without_spooling(self):
        self.inner.up = True
        self.assertTrue(self.rel.deliver(make_alert(1)))
        self.assertEqual(self.rel.pending_count, 0)
        self.assertEqual(self.rel.stats["delivered"], 1)
        self.assertEqual(self.rel.stats["spooled"], 0)

    def test_destination_name_matches_inner(self):
        self.assertEqual(self.rel.destination_name, "FlakyDestination")

    # ── outage -> spool -> recovery ──────────────────────────────────────────
    def test_failure_is_spooled_not_lost(self):
        a = make_alert(2)
        self.assertFalse(self.rel.deliver(a))
        self.assertEqual(self.rel.pending_count, 1)
        self.assertEqual(self.rel.stats["spooled"], 1)

    def test_recovery_delivers_spooled_alert(self):
        a = make_alert(3)
        self.rel.deliver(a)
        self.inner.up = True
        self.clock.advance(10)
        self.assertEqual(self.rel.flush(), 1)
        self.assertEqual(self.rel.pending_count, 0)
        self.assertEqual(self.inner.received, [a.alert_id])
        self.assertEqual(self.rel.stats["recovered"], 1)

    def test_inner_exception_is_treated_as_outage(self):
        self.inner.raise_on_fail = True
        self.assertFalse(self.rel.deliver(make_alert(4)))
        self.assertEqual(self.rel.pending_count, 1)

    # ── exponential backoff ──────────────────────────────────────────────────
    def test_backoff_schedule_doubles_and_caps(self):
        self.assertEqual([self.rel.backoff_delay(n) for n in (1, 2, 3, 4, 5, 6)],
                         [1.0, 2.0, 4.0, 8.0, 8.0, 8.0])

    def test_retry_not_attempted_before_backoff_elapses(self):
        self.rel.deliver(make_alert(5))
        calls_before = self.inner.calls
        self.clock.advance(0.5)  # < 1s base delay
        self.assertEqual(self.rel.flush(), 0)
        self.assertEqual(self.inner.calls, calls_before)

    def test_backoff_grows_between_failed_retries(self):
        a = make_alert(6)
        self.rel.deliver(a)
        path = self.rel._path(self.rel.spool_dir, a.alert_id)
        gaps = []
        for _ in range(2):
            before = self.clock()
            self.clock.advance(100)
            self.rel.flush()
            rec = json.loads(path.read_text())
            gaps.append(rec["next_attempt_at"] - self.clock())
        self.assertEqual(gaps, [self.rel.backoff_delay(2), self.rel.backoff_delay(3)])

    def test_force_flush_ignores_backoff(self):
        self.rel.deliver(make_alert(7))
        self.inner.up = True
        self.assertEqual(self.rel.flush(force=True), 1)

    # ── dead-letter queue ────────────────────────────────────────────────────
    def test_exhausted_alert_moves_to_dlq_not_dropped(self):
        a = make_alert(8)
        self.rel.deliver(a)  # attempt 1
        for _ in range(10):
            self.clock.advance(100)
            self.rel.flush()
        self.assertEqual(self.rel.pending_count, 0)
        self.assertEqual(self.rel.dead_letter_count, 1)
        self.assertEqual(self.rel.stats["dead_lettered"], 1)
        dlq = json.loads(self.rel._path(self.rel.dlq_dir, a.alert_id).read_text())
        self.assertEqual(dlq["alert"]["alert_id"], a.alert_id)
        self.assertEqual(dlq["attempts"], self.rel.max_attempts)

    def test_dlq_replay_after_recovery_delivers(self):
        a = make_alert(9)
        self.rel.deliver(a)
        for _ in range(10):
            self.clock.advance(100)
            self.rel.flush()
        self.assertEqual(self.rel.dead_letter_count, 1)
        self.inner.up = True
        self.assertEqual(self.rel.replay_dead_letters(), 1)
        self.assertEqual(self.rel.flush(force=True), 1)
        self.assertEqual(self.rel.dead_letter_count, 0)
        self.assertEqual(self.inner.received, [a.alert_id])

    def test_corrupt_spool_file_is_quarantined_not_crashing(self):
        (self.rel.spool_dir / "garbage.json").write_text("{not json")
        self.rel.deliver(make_alert(10))
        self.inner.up = True
        self.clock.advance(100)
        self.assertEqual(self.rel.flush(), 1)  # good alert still delivered
        self.assertEqual(self.rel.dead_letter_count, 1)  # corrupt one quarantined

    # ── idempotency ──────────────────────────────────────────────────────────
    def test_same_alert_submitted_twice_while_down_spools_once(self):
        a = make_alert(11)
        self.rel.deliver(a)
        self.rel.deliver(a)
        self.assertEqual(self.rel.pending_count, 1)
        self.assertEqual(self.rel.stats["duplicates_suppressed"], 1)

    def test_already_delivered_alert_is_not_sent_twice(self):
        self.inner.up = True
        a = make_alert(12)
        self.assertTrue(self.rel.deliver(a))
        self.assertTrue(self.rel.deliver(a))
        self.assertEqual(self.inner.received, [a.alert_id])

    def test_no_double_delivery_after_recovery(self):
        a = make_alert(13)
        self.rel.deliver(a)
        self.inner.up = True
        self.clock.advance(100)
        self.rel.flush()
        self.rel.flush(force=True)
        self.rel.deliver(a)
        self.assertEqual(self.inner.received.count(a.alert_id), 1)

    # ── durability ───────────────────────────────────────────────────────────
    def test_spool_survives_process_restart(self):
        alerts = [make_alert(20 + i) for i in range(5)]
        for a in alerts:
            self.rel.deliver(a)
        # "crash": throw away the wrapper, build a new one on the same directory
        inner2 = FlakyDestination()
        inner2.up = True
        rel2 = ReliableAlertDestination(inner2, self.tmp.name, max_attempts=4, clock=self.clock)
        self.assertEqual(rel2.pending_count, 5)
        self.clock.advance(100)
        self.assertEqual(rel2.flush(), 5)
        self.assertEqual(sorted(inner2.received), sorted(a.alert_id for a in alerts))

    def test_malicious_alert_id_cannot_escape_spool_dir(self):
        a = make_alert(30)
        a.alert_id = "../../../evil"
        self.rel.deliver(a)
        written = list(Path(self.tmp.name).rglob("*.json"))
        self.assertTrue(written)
        for p in written:
            self.assertTrue(str(p.resolve()).startswith(str(Path(self.tmp.name).resolve())))

    def test_invalid_max_attempts_rejected(self):
        with self.assertRaises(ValueError):
            ReliableAlertDestination(self.inner, self.tmp.name, max_attempts=0)

    # ── concurrency ──────────────────────────────────────────────────────────
    def test_concurrent_producers_lose_nothing(self):
        alerts = [make_alert(100 + i) for i in range(60)]
        threads = [threading.Thread(target=self.rel.deliver, args=(a,)) for a in alerts]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(self.rel.pending_count, 60)
        self.inner.up = True
        self.clock.advance(100)
        self.rel.flush()
        self.assertEqual(sorted(self.inner.received), sorted(a.alert_id for a in alerts))

    def test_background_worker_drains_spool(self):
        rel = ReliableAlertDestination(
            self.inner, Path(self.tmp.name) / "bg", max_attempts=50,
            base_delay_seconds=0.01, max_delay_seconds=0.02,
        )
        alerts = [make_alert(200 + i) for i in range(5)]
        for a in alerts:
            rel.deliver(a)
        rel.start_background(interval_seconds=0.02)
        self.inner.up = True
        deadline = time.time() + 5
        while time.time() < deadline and rel.pending_count:
            time.sleep(0.05)
        rel.stop_background()
        self.assertEqual(rel.pending_count, 0)
        self.assertEqual(len(self.inner.received), 5)


class TestRouterIntegration(unittest.TestCase):
    """The wrapper must plug into AlertRouter without changing its behaviour."""

    def test_router_dedup_still_applies_and_other_destinations_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock()
            inner = FlakyDestination()
            rel = ReliableAlertDestination(inner, tmp, clock=clock)
            mem = MemoryAlertDestination()
            router = AlertRouter(destinations=[mem, rel], min_severity="P4_INFO", dedup_window_seconds=60)

            a = make_alert(1, severity="P3_WARNING", camera="cam-same")
            b = make_alert(1, severity="P3_WARNING", camera="cam-same")  # same camera+threat
            router.route_alert(a)
            router.route_alert(b)  # deduplicated by the router before reaching wrapper

            self.assertEqual(mem.count, 1)  # unaffected destination got it exactly once
            self.assertEqual(rel.pending_count, 1)  # SIEM was down -> spooled, once
            self.assertEqual(router.total_dropped_dedup, 1)

    def test_router_reports_false_for_spooled_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = ReliableAlertDestination(FlakyDestination(), tmp, clock=FakeClock())
            router = AlertRouter(destinations=[rel], min_severity="P4_INFO")
            res = router.route_alert(make_alert(2))
            self.assertEqual(res, {"FlakyDestination": False})


class _SiemHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.received.append(json.loads(body)["alert_id"])
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class _SiemMock:
    """A real HTTP SIEM that can be killed and restarted on the same port."""

    def __init__(self, port=0):
        self.received = []
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        self.server = HTTPServer(("127.0.0.1", self.port), _SiemHandler)
        self.server.received = self.received
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def kill(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class TestKillSiemMidRun(unittest.TestCase):
    """HEADLINE PROOF: kill the SIEM mid-run, keep alerting, recover, zero lost alerts."""

    def test_zero_lost_alerts_across_siem_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            siem = _SiemMock()
            siem.start()
            port = siem.port

            webhook = WebhookAlertDestination(
                endpoint_url=f"http://127.0.0.1:{port}/alerts", timeout_seconds=0.5
            )
            rel = ReliableAlertDestination(
                webhook, tmp, max_attempts=30, base_delay_seconds=0.05, max_delay_seconds=0.2
            )
            mem = MemoryAlertDestination()
            router = AlertRouter(destinations=[mem, rel], min_severity="P4_INFO", dedup_window_seconds=0.0)

            sent = []

            def fire(start, count):
                for i in range(start, start + count):
                    a = make_alert(i, camera=f"cam-kill-{i}")
                    sent.append(a.alert_id)
                    router.route_alert(a)

            fire(0, 10)  # phase 1: SIEM up
            self.assertEqual(len(siem.received), 10)

            siem.kill()  # phase 2: SIEM dies mid-run
            fire(10, 15)
            self.assertEqual(len(siem.received), 10)  # nothing reached it
            self.assertEqual(rel.pending_count, 15)  # ...but nothing was lost
            self.assertEqual(mem.count, 25)  # other destinations unaffected

            time.sleep(0.3)
            rel.flush()  # still down: stays queued, no loss
            self.assertEqual(rel.pending_count, 15)

            siem2 = _SiemMock(port=port)  # phase 3: SIEM recovers on same port
            siem2.received = siem.received
            siem2.start()
            self.addCleanup(siem2.kill)

            deadline = time.time() + 10
            while time.time() < deadline and rel.pending_count:
                time.sleep(0.2)
                rel.flush()

            self.assertEqual(rel.pending_count, 0)
            self.assertEqual(rel.dead_letter_count, 0)
            self.assertEqual(sorted(siem.received), sorted(sent), "every alert must arrive exactly once")
            self.assertEqual(len(siem.received), len(set(siem.received)), "no duplicates")


if __name__ == "__main__":
    unittest.main()

