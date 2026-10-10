#!/usr/bin/env bash
# Every language the engine supports beyond Python and Node, and the test
# runner each one needs. Idempotent.
#
# DESIGN section 7: the engine does not know languages, adapters do. An
# adapter needs two things from the machine -- the language itself, and
# something that runs tests one at a time in isolation. Nothing more: the
# verdict is read from the comparison function's record, not from the test
# framework's report, so the framework's output format does not matter.
#
# Go, Rust, Java, Ruby and PHP were first installed by hand (the apt history
# shows `apt install -y golang-go rustc cargo default-jdk ruby-full` and
# `php php-cli`). Nothing here recorded them, so a rebuilt box would have come
# up without them and nobody would have been told. This script is that record.
#
# Machine only (SYSTEM 8-1). Nothing here touches a project directory: the
# per-project files a language needs (go.mod, Cargo.toml, a phpunit config ...)
# are the adapter's to write when the window builds a workspace.
#
# Python and Node are not repeated here; 30-python.sh and 35-node.sh own them.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# One test runner per language, the one a model is most likely to have seen:
#
#   Go          `go test`            standard library
#   Rust        `cargo test`         standard library (libtest)
#   Java        JUnit 5              junit5 -- the console launcher runs it
#   Ruby        minitest             ships with Ruby
#   PHP         PHPUnit              phpunit
#   Perl        Test::More / prove   ships with Perl
#   C / C++     GoogleTest           libgtest-dev. C has no test framework of
#                                    its own worth the name; C code is linked
#                                    into a C++ GoogleTest binary and called
#                                    through extern "C".
#
# headless JDK: there is no display here (WSLg is off, provision/README 3-8).
apt-get update -qq
apt-get install -y -qq \
  golang-go \
  rustc cargo \
  default-jdk-headless junit5 \
  ruby ruby-minitest \
  php-cli phpunit \
  perl \
  gcc g++ make libgtest-dev

JUNIT_JAR="$(ls /usr/share/java/junit-platform-console-standalone*.jar 2>/dev/null | head -1 || true)"
if [ -z "$JUNIT_JAR" ]; then
  echo "36-languages: junit5 did not install a console launcher under /usr/share/java" >&2
  exit 1
fi

# ---- assertions: each runner, in both directions ---------------------------
#
# A runner that reports every test as passing is indistinguishable from one
# that works (provision/README 2-5 says the same of smoke-dom). So each
# language runs one test that must pass and one that must fail, and both
# outcomes are checked.
#
# They run as exec -- the account tests and generated code run under -- from a
# scratch directory exec owns, not from wherever this script was started
# (README 3-14). This runs after 25-egress.sh, so exec has no network at all
# while it does it: Go is told there is no module proxy and cargo that it is
# offline, and the run proves that is enough.
#
# Note for the adapters: exec may READ a workspace but not write one, so
# anything a build produces (javac -d, g++ -o, cargo's target/, Go's cache)
# has to go under exec's home or a scratch directory of its own, as it does
# here.
W="$(sudo -u exec mktemp -d /tmp/lang-smoke.XXXXXX)"
trap 'rm -rf "$W"' EXIT
LOG="$W/.log"
fail=0

put() {  # put <relative path>  (contents on stdin), owned by exec
  sudo -u exec install -d "$W/$(dirname "$1")"
  sudo -u exec tee "$W/$1" >/dev/null
}

expect() {  # expect pass|fail <label> <command...>
  local want="$1" label="$2" got
  shift 2
  if sudo -u exec -H env -C "$W" GOPROXY=off GOTOOLCHAIN=local GOFLAGS=-mod=mod \
       CARGO_TARGET_DIR="$W/target" "$@" >"$LOG" 2>&1; then
    got=pass
  else
    got=fail
  fi
  if [ "$got" = "$want" ]; then
    echo "  ok    $label: $want"
  else
    echo "  FAIL  $label: expected $want, got $got" >&2
    sed 's/^/        /' "$LOG" | tail -15 >&2
    fail=1
  fi
}

echo "smoke tests in $W"

# Go
put go/go.mod <<'EOF'
module smoke

go 1.22
EOF
put go/smoke_test.go <<'EOF'
package smoke

import "testing"

func TestPass(t *testing.T) {
	if 1+1 != 2 {
		t.Fatal("arithmetic")
	}
}

func TestFail(t *testing.T) {
	t.Fatal("this test must fail")
}
EOF
expect pass "go test"   bash -c 'cd go && go test -run "^TestPass$" ./...'
expect fail "go test"   bash -c 'cd go && go test -run "^TestFail$" ./...'

# Rust
put rust/Cargo.toml <<'EOF'
[package]
name = "smoke"
version = "0.1.0"
edition = "2021"
EOF
put rust/src/lib.rs <<'EOF'
#[cfg(test)]
mod t {
    #[test]
    fn pass() {
        assert_eq!(1 + 1, 2);
    }

    #[test]
    fn fail() {
        assert_eq!(1, 2);
    }
}
EOF
expect pass "cargo test" bash -c 'cd rust && cargo test --offline --quiet -- --exact t::pass'
expect fail "cargo test" bash -c 'cd rust && cargo test --offline --quiet -- --exact t::fail'

# Java
put java/SmokeTest.java <<'EOF'
import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

public class SmokeTest {
    @Test
    void pass() {
        assertEquals(2, 1 + 1);
    }

    @Test
    void fail() {
        assertEquals(1, 2);
    }
}
EOF
expect pass "javac"     bash -c "cd java && javac -cp '$JUNIT_JAR' -d out SmokeTest.java"
expect pass "junit"     bash -c "cd java && java -jar '$JUNIT_JAR' execute --disable-banner --class-path out --select-method SmokeTest#pass"
expect fail "junit"     bash -c "cd java && java -jar '$JUNIT_JAR' execute --disable-banner --class-path out --select-method SmokeTest#fail"

# Ruby
put ruby/smoke_test.rb <<'EOF'
require "minitest/autorun"

class SmokeTest < Minitest::Test
  def test_pass
    assert_equal 2, 1 + 1
  end

  def test_fail
    assert_equal 1, 2
  end
end
EOF
expect pass "minitest"  bash -c 'cd ruby && ruby smoke_test.rb -n test_pass'
expect fail "minitest"  bash -c 'cd ruby && ruby smoke_test.rb -n test_fail'

# PHP
put php/SmokeTest.php <<'EOF'
<?php
use PHPUnit\Framework\TestCase;

final class SmokeTest extends TestCase
{
    public function testPass(): void
    {
        $this->assertSame(2, 1 + 1);
    }

    public function testFail(): void
    {
        $this->assertSame(1, 2);
    }
}
EOF
expect pass "phpunit"   bash -c 'cd php && phpunit --filter "testPass$" SmokeTest.php'
expect fail "phpunit"   bash -c 'cd php && phpunit --filter "testFail$" SmokeTest.php'

# Perl
put perl/pass.t <<'EOF'
use strict;
use warnings;
use Test::More tests => 1;
is(1 + 1, 2);
EOF
put perl/fail.t <<'EOF'
use strict;
use warnings;
use Test::More tests => 1;
is(1, 2);
EOF
expect pass "prove"     bash -c 'cd perl && prove pass.t'
expect fail "prove"     bash -c 'cd perl && prove fail.t'

# C and C++, through GoogleTest
put cc/add.c <<'EOF'
int add(int a, int b) { return a + b; }
EOF
put cc/smoke_test.cc <<'EOF'
#include <gtest/gtest.h>

extern "C" int add(int a, int b);

TEST(Smoke, Pass) { EXPECT_EQ(add(1, 1), 2); }
TEST(Smoke, Fail) { EXPECT_EQ(add(1, 1), 3); }
EOF
expect pass "gcc + g++" bash -c 'cd cc && gcc -c add.c -o add.o && g++ -std=c++17 smoke_test.cc add.o -lgtest -lgtest_main -pthread -o smoke'
expect pass "gtest"     bash -c 'cd cc && ./smoke --gtest_filter=Smoke.Pass'
expect fail "gtest"     bash -c 'cd cc && ./smoke --gtest_filter=Smoke.Fail'

echo
echo "versions:"
echo "  $(go version)"
echo "  $(rustc --version) / $(cargo --version)"
echo "  java $(java -version 2>&1 | head -1) / $(basename "$JUNIT_JAR")"
echo "  $(ruby --version) / minitest $(ruby -e 'require "minitest"; print Minitest::VERSION')"
echo "  $(php --version | head -1) / $(phpunit --version | head -1)"
echo "  perl $(perl -e 'print $^V') / Test::More $(perl -MTest::More -e 'print $Test::More::VERSION')"
echo "  $(gcc --version | head -1) / gtest $(dpkg-query -W -f='${Version}' libgtest-dev)"

if [ "$fail" -eq 0 ]; then
  echo "36-languages: ok (all assertions passed)"
else
  echo "36-languages: A TEST RUNNER DOES NOT BEHAVE" >&2
fi
exit "$fail"
