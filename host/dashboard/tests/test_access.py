"""The Host header decides who is asking.

It is the one value a DNS-rebound request cannot forge, which is why the
loopback check leans on it -- and once the dashboard is published to a tailnet,
it is also what separates "at the machine" from "on a phone". Both answers come
from the same place for the same reason.
"""

import json
import tempfile
import unittest
from pathlib import Path

from host.dashboard.access import LOCAL, REMOTE, Reach

PUBLISHED = "server.example.ts.net:8443"
OWNER = "someone@example.com"


class ReachFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "config.json"
        self.reach = Reach(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, **remote):
        self.config.write_text(json.dumps({"remote": remote}), encoding="utf-8")

    def of(self, host, user=None):
        headers = {"Host": host}
        if user is not None:
            headers["Tailscale-User-Login"] = user
        return self.reach.of(headers)


class AtTheMachine(ReachFixture):
    def test_the_loopback_names_are_local_with_no_configuration_at_all(self):
        for host in ("127.0.0.1:8443", "localhost:8443", "[::1]:8443", "127.0.0.1"):
            self.assertEqual(self.of(host), (LOCAL, ""), host)

    def test_a_rebound_name_is_refused_even_though_it_resolves_to_loopback(self):
        for host in ("dashboard.attacker.example:8443", "127.0.0.1.attacker.example", ""):
            self.assertEqual(self.of(host), (None, ""), host)


class OverTheTailnet(ReachFixture):
    def test_the_published_name_with_a_known_person_behind_it(self):
        self.publish(host=PUBLISHED, users=[OWNER])
        self.assertEqual(self.of(PUBLISHED, OWNER), (REMOTE, OWNER))

    def test_the_identity_the_proxy_wrote_has_to_be_one_that_was_listed(self):
        self.publish(host=PUBLISHED, users=[OWNER])
        self.assertEqual(self.of(PUBLISHED, "someone-else@example.com"), (None, ""))
        self.assertEqual(self.of(PUBLISHED), (None, ""))

    def test_an_unpublished_dashboard_answers_to_loopback_only(self):
        self.assertEqual(self.of(PUBLISHED, OWNER), (None, ""))

    def test_publishing_without_naming_anyone_publishes_to_no_one(self):
        # Fail closed. An empty list is not "everybody".
        self.publish(host=PUBLISHED)
        self.assertEqual(self.of(PUBLISHED, OWNER), (None, ""))
        self.publish(host=PUBLISHED, users=[])
        self.assertEqual(self.of(PUBLISHED, OWNER), (None, ""))

    def test_a_second_service_on_the_same_machine_is_still_a_different_name(self):
        self.publish(host=PUBLISHED, users=[OWNER])
        self.assertEqual(self.of("other.example.ts.net:8443", OWNER), (None, ""))


if __name__ == "__main__":
    unittest.main()
