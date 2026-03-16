# Test Guardrails

- UI, `MainWindow`, and `ServiceLocator` tests must not use the real default project store at `C:\Users\Administrator\.h2ometa` or `~/.h2ometa`.
- In tests, always inject a temporary `ProjectManager`, for example with `projects_root=tmp_path / "projects"` and `index_path=tmp_path / "projects.json"`.
- On Windows, if `pytest` fails while cleaning `--basetemp` or another temporary directory with `WinError 5` or a similar permission error, do not stop at the first error report.
- In that case, request escalation, clean the temporary directory, and rerun the relevant test command.
