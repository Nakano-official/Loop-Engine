"""The Host header is the only thing a DNS-rebound request cannot forge."""

import unittest

from host.dashboard.server import handler_for


class HostHeader(unittest.TestCase):
    def setUp(self):
        self.handler = handler_for(state=None, launchers=None, token="unused")

    def check(self, value: str) -> bool:
        # __new__ on purpose: BaseHTTPRequestHandler.__init__ serves a request.
        # The predicate reads self.headers and nothing else.
        handler = self.handler.__new__(self.handler)
        handler.headers = {"Host": value}
        return handler._local_host()

    def test_the_loopback_names_this_server_answers_to(self):
        for value in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765", "127.0.0.1"):
            self.assertTrue(self.check(value), value)

    def test_a_rebound_name_is_refused_even_though_it_resolves_to_loopback(self):
        for value in ("dashboard.attacker.example:8765", "127.0.0.1.attacker.example",
                      "192.168.1.20:8765", ""):
            self.assertFalse(self.check(value), value)


if __name__ == "__main__":
    unittest.main()
