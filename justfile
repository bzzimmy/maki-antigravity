default:
    @just --list

check:
    cargo check --tests
    python3 -m py_compile proxy/antigravity_proxy.py

lint:
    cargo clippy --tests -- -D warnings

test: test-py
    cargo nextest run

test-py:
    python3 -m unittest discover -s tests -p 'test_*.py'

fmt-lua:
    stylua plugin/
