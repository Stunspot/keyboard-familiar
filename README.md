# Keyboard Familiar Harness (v1 skeleton)

A debug-first modular monolith for event -> state -> decision -> directive -> surface pipelines.

## Quickstart

```bash
pip install -e .[dev]
familiar trigger test.ping --source manual --message "hello"
familiar state show
familiar trace tail --lines 20
```

## Runtime mode

`familiar run` starts a long-running loop and keeps the harness process alive until `Ctrl+C`.

For quick terminal proof without running a daemon, `trigger` persists state/trace to
`.familiar/runtime.json`, and `state show` / `trace tail` read from the same file.
familiar run
familiar trigger test.ping --source manual
familiar state show
familiar trace tail --lines 20
