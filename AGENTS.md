# Agent Notes

## Mac/Linux Sync Workflow

This project is developed locally on macOS at:

```text
/Users/pporacle/Documents/GitHub/Exawatcher_ParserTool
```

The matching Linux workspace is:

```text
ssh paportug@phoenix93718.dev3sub2phx.databasede3phx.oraclevcn.com
/home/paportug/GitHub/Exawatcher_ParserTool
```

SSH key access is configured and does not require a password.

Desired branch model:

- `macos`: primary local development branch on this Mac.
- `linux`: Linux-side branch/worktree for the remote Linux box.

When the user asks to sync this project:

1. Commit local macOS changes on the `macos` branch.
2. Push/sync the committed code to the Linux box.
3. Keep the Linux copy at `/home/paportug/GitHub/Exawatcher_ParserTool`.
4. Preserve separate branches named `macos` and `linux` so OS-specific fixes can remain isolated when needed.
5. Do not assume destructive git operations are allowed; ask before overwriting, resetting, or deleting remote work.

