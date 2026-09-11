default:
    @just --list

check:
    cargo check --tests
    python3 -m py_compile providers/antigravity

lint:
    cargo clippy --tests -- -D warnings

test: test-py
    cargo nextest run

test-py:
    python3 -m unittest discover -s tests -p 'test_*.py'

fmt-lua:
    stylua plugin/
