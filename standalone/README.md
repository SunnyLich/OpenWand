# Standalone Agent Team runner

This entry point exercises OpenWand's scoped Agent Team engine without launching
Qt, the overlay, or any OpenWand worker process.

OpenWand chat uses this detached contract when its model delegates substantial
project work in the background. That automatic chat launch is separate from
the user-configured **Start Agent Team...** window, even though both reuse the
same scoped execution engine.

Run the deterministic offline proof (no API key or network required):

```powershell
python -m standalone.background_agents demo --workspace .tmp\agent-demo
```

Prove that a job continues after its launcher exits:

```powershell
python -m standalone.background_agents start-demo `
  --workspace .tmp\agent-demo `
  --state .tmp\agent-demo-job.json
python -m standalone.background_agents status `
  --state .tmp\agent-demo-job.json
```

Run a real task contract with the provider/model configured for OpenWand:

```powershell
python -m standalone.background_agents start `
  --spec path\to\task.json `
  --state .tmp\my-agent-job.json
```

The state JSON records the PID, lifecycle status, latest log line, run folder,
and final report path. Agent file access remains constrained by the scope and
permissions in the task spec. A headless run cannot display approval prompts,
so approval-gated actions are declined; use OpenWand's UI when interactive approval
is required.
